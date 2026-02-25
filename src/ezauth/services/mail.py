import asyncio
import os
from typing import Any

import boto3
import chevron
import premailer
from loguru import logger

from ezauth.config import settings

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mail", "templates")


class MailError(Exception):
    pass


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
        template_html = self._build_html_template(template)
        html = chevron.render(template_html, data)

        text = None
        template_text = self._build_text_template(template)
        if template_text is not None:
            text = chevron.render(template_text, data)

        return await self.send(to, subject, html=html, text=text)

    def _build_html_template(self, name: str) -> str:
        cache_key = f"html:{name}"
        if cache_key not in self._template_cache:
            base_html = self._load_template("base", "html")
            main_html = self._load_template(name, "html")
            html = chevron.render(base_html, {
                "main": main_html,
                "summary": "{{{ summary }}}",
            })
            html = premailer.transform(html, preserve_handlebar_syntax=True)
            self._template_cache[cache_key] = html
        return self._template_cache[cache_key]

    def _build_text_template(self, name: str) -> str | None:
        cache_key = f"text:{name}"
        if cache_key not in self._template_cache:
            base_text = self._load_template_optional("base", "txt")
            main_text = self._load_template_optional(name, "txt")
            if main_text is None:
                self._template_cache[cache_key] = ""
                return None
            if base_text is not None:
                text = chevron.render(base_text, {
                    "main": main_text,
                    "summary": "{{{ summary }}}",
                })
            else:
                text = main_text
            self._template_cache[cache_key] = text
        result = self._template_cache[cache_key]
        return result if result else None

    # Keep backward-compatible alias
    def build_template(self, name: str) -> str:
        return self._build_html_template(name)

    def _load_template(self, name: str, ext: str = "html") -> str:
        path = os.path.join(self.templates_dir, f"{name}.{ext}")
        if not os.path.isfile(path):
            raise MailError(f"Template not found: {name}.{ext}")
        with open(path) as fp:
            return fp.read()

    def _load_template_optional(self, name: str, ext: str = "html") -> str | None:
        path = os.path.join(self.templates_dir, f"{name}.{ext}")
        if not os.path.isfile(path):
            return None
        with open(path) as fp:
            return fp.read()
