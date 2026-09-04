"""Transactional email: template assembly and SES delivery.

Each message is a named Mustache template wrapped in `base`, rendered with
chevron and inlined with premailer, then handed to SES. Template sources come
from the packaged `mail/templates` directory unless an `EmailTemplate` row
overrides them: overrides live in Postgres so an edit made in the dashboard
survives a redeploy and is picked up by every instance, without needing a
writable package directory.

Assembling a template is expensive, so results are cached on the class. The
cache key carries the `updated_at` of each override involved, which means a
saved edit produces a new key and takes effect immediately, and the cache
cannot serve a stale body. Reading the overrides is best-effort: if the lookup
fails the packaged files are used rather than failing the send.
"""

import asyncio
import os
from typing import Any

import boto3
import chevron
import premailer
from loguru import logger
from sqlalchemy import select

from ezauth.config import settings
from ezauth.db.engine import async_session_factory
from ezauth.models.email_template import EmailTemplate

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mail", "templates")

BASE_TEMPLATE = "base"
_MAX_CACHE_ENTRIES = 64


class MailError(Exception):
    pass


async def load_overrides(names: list[str]) -> dict[tuple[str, str], tuple[str, str]]:
    """Override content and version, keyed by (name, format)."""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(EmailTemplate).where(EmailTemplate.name.in_(names))
            )
            return {
                (row.name, row.format): (row.content, row.updated_at.isoformat())
                for row in result.scalars().all()
            }
    except Exception:
        logger.warning("Could not read email template overrides; using packaged templates")
        return {}


class MailService:
    # Class-level template cache shared across all instances to avoid
    # re-loading and re-rendering templates on every request.
    _template_cache: dict[str, str] = {}

    def __init__(
        self,
        *,
        sender_name: str | None = None,
        sender_address: str | None = None,
        region: str | None = None,
        templates_dir: str | None = None,
    ):
        self.sender_name = sender_name or settings.ses_sender_name
        self.sender_address = sender_address or settings.ses_sender
        self.region = region or settings.ses_region
        self.source_addr = f"{self.sender_name} <{self.sender_address}>"
        self.templates_dir = templates_dir or TEMPLATES_DIR
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client("ses", region_name=self.region)
        return self._client

    async def send(
        self,
        to: str,
        subject: str,
        *,
        html: str | None = None,
        text: str | None = None,
    ) -> dict:
        destination = {"ToAddresses": [to]}
        message: dict[str, Any] = {
            "Subject": {"Charset": settings.mail_charset, "Data": subject},
            "Body": {},
        }

        if html:
            message["Body"]["Html"] = {"Charset": settings.mail_charset, "Data": html}
        if text:
            message["Body"]["Text"] = {"Charset": settings.mail_charset, "Data": text}

        if not message["Body"]:
            raise MailError("No message content")

        logger.info(f"Sending email to {to}")

        def _send():
            return self.client.send_email(
                Destination=destination,
                Message=message,
                Source=self.source_addr,
            )

        return await asyncio.to_thread(_send)

    async def send_template(
        self,
        template: str,
        to: str,
        subject: str,
        data: dict,
    ) -> dict:
        overrides = await load_overrides([BASE_TEMPLATE, template])
        template_html = self._build_html_template(template, overrides)
        html = chevron.render(template_html, data)

        text = None
        template_text = self._build_text_template(template, overrides)
        if template_text is not None:
            text = chevron.render(template_text, data)

        return await self.send(to, subject, html=html, text=text)

    def _cache_key(self, kind: str, name: str, overrides: dict) -> str:
        versions = [
            f"{key[0]}.{key[1]}={value[1]}"
            for key, value in sorted(overrides.items())
            if key[0] in (BASE_TEMPLATE, name)
        ]
        return f"{kind}:{name}:{'|'.join(versions)}"

    def _cache_put(self, key: str, value: str) -> None:
        if len(self._template_cache) >= _MAX_CACHE_ENTRIES:
            self._template_cache.clear()
        self._template_cache[key] = value

    def _build_html_template(self, name: str, overrides: dict | None = None) -> str:
        overrides = overrides or {}
        cache_key = self._cache_key("html", name, overrides)
        if cache_key not in self._template_cache:
            base_html = self._load_template(BASE_TEMPLATE, "html", overrides)
            main_html = self._load_template(name, "html", overrides)
            html = chevron.render(base_html, {
                "main": main_html,
                "summary": "{{{ summary }}}",
            })
            html = premailer.transform(html, preserve_handlebar_syntax=True)
            self._cache_put(cache_key, html)
        return self._template_cache[cache_key]

    def _build_text_template(self, name: str, overrides: dict | None = None) -> str | None:
        overrides = overrides or {}
        cache_key = self._cache_key("text", name, overrides)
        if cache_key not in self._template_cache:
            base_text = self._load_template_optional(BASE_TEMPLATE, "txt", overrides)
            main_text = self._load_template_optional(name, "txt", overrides)
            if main_text is None:
                self._cache_put(cache_key, "")
                return None
            if base_text is not None:
                text = chevron.render(base_text, {
                    "main": main_text,
                    "summary": "{{{ summary }}}",
                })
            else:
                text = main_text
            self._cache_put(cache_key, text)
        result = self._template_cache[cache_key]
        return result if result else None

    def build_template(self, name: str) -> str:
        return self._build_html_template(name)

    def _load_template(self, name: str, ext: str = "html", overrides: dict | None = None) -> str:
        source = self._load_template_optional(name, ext, overrides)
        if source is None:
            raise MailError(f"Template not found: {name}.{ext}")
        return source

    def _load_template_optional(
        self, name: str, ext: str = "html", overrides: dict | None = None
    ) -> str | None:
        override = (overrides or {}).get((name, ext))
        if override is not None:
            return override[0]
        path = os.path.join(self.templates_dir, f"{name}.{ext}")
        if not os.path.isfile(path):
            return None
        with open(path) as fp:
            return fp.read()
