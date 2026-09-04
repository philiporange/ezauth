"""Dashboard editor for the instance-wide mail templates.

The packaged files under `mail/templates` are the defaults and are never
written to: an edit is stored as an `EmailTemplate` row, so it survives a
redeploy, is shared by every instance and needs no writable package directory.
Reverting deletes the row and the packaged default takes over again. Only names
that correspond to a packaged template are editable, which keeps the name a
plain identifier and leaves no way to reach the filesystem through it.
"""

import os
import pathlib
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from ezauth.dashboard.auth import DashboardAuth, require_superadmin, templates
from ezauth.dependencies import DbSession
from ezauth.models.email_template import EmailTemplate

router = APIRouter()

MAIL_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "mail" / "templates"

BASE_TEMPLATE = "base"
TEMPLATE_FORMAT = "html"

_SAFE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _packaged_names() -> list[str]:
    """Editable template names shipped with the package."""
    if not MAIL_TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        path.stem
        for path in MAIL_TEMPLATES_DIR.glob(f"*.{TEMPLATE_FORMAT}")
        if path.stem != BASE_TEMPLATE
    )


def _packaged_path(name: str) -> pathlib.Path:
    """Path of the packaged default, rejecting anything that is not one."""
    if not _SAFE_NAME_RE.match(name) or name == BASE_TEMPLATE:
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = MAIL_TEMPLATES_DIR / f"{name}.{TEMPLATE_FORMAT}"
    if os.path.realpath(path.parent) != os.path.realpath(MAIL_TEMPLATES_DIR):
        raise HTTPException(status_code=400, detail="Invalid template name")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown template")
    return path


async def _get_override(db: DbSession, name: str) -> EmailTemplate | None:
    result = await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.name == name, EmailTemplate.format == TEMPLATE_FORMAT
        )
    )
    return result.scalars().first()


@router.get("", response_class=HTMLResponse)
async def list_email_templates(
    request: Request,
    db: DbSession,
    auth: DashboardAuth = Depends(require_superadmin),
):
    result = await db.execute(
        select(EmailTemplate.name).where(EmailTemplate.format == TEMPLATE_FORMAT)
    )
    overridden = set(result.scalars().all())
    return templates.TemplateResponse(
        "email_editor/list.html",
        {
            "request": request,
            "template_files": _packaged_names(),
            "overridden": overridden,
            "auth": auth,
        },
    )


@router.get("/{name}", response_class=HTMLResponse)
async def edit_email_template(
    name: str,
    request: Request,
    db: DbSession,
    auth: DashboardAuth = Depends(require_superadmin),
):
    path = _packaged_path(name)
    override = await _get_override(db, name)
    content = override.content if override else path.read_text()

    return templates.TemplateResponse(
        "email_editor/edit.html",
        {
            "request": request,
            "name": name,
            "content": content,
            "is_override": override is not None,
            "auth": auth,
        },
    )


@router.post("/{name}")
async def save_email_template(
    name: str,
    request: Request,
    db: DbSession,
    auth: DashboardAuth = Depends(require_superadmin),
):
    _packaged_path(name)
    form = await request.form()
    content = form.get("content", "")

    override = await _get_override(db, name)
    if override is None:
        db.add(EmailTemplate(name=name, format=TEMPLATE_FORMAT, content=content))
    else:
        override.content = content
    await db.flush()
    return HTMLResponse('<span class="text-success">Saved!</span>')


@router.post("/{name}/reset")
async def reset_email_template(
    name: str,
    request: Request,
    db: DbSession,
    auth: DashboardAuth = Depends(require_superadmin),
):
    _packaged_path(name)
    override = await _get_override(db, name)
    if override is not None:
        await db.delete(override)
        await db.flush()
    return HTMLResponse('<span class="text-success">Reverted to the packaged default.</span>')
