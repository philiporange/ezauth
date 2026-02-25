import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ezauth.dashboard.auth import require_dashboard_auth

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")

MAIL_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "mail", "templates"
)

_SAFE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _validate_template_name(name: str) -> str:
    """Validate template name to prevent path traversal."""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    path = os.path.join(MAIL_TEMPLATES_DIR, f"{name}.html")
    if not os.path.realpath(path).startswith(os.path.realpath(MAIL_TEMPLATES_DIR)):
        raise HTTPException(status_code=400, detail="Invalid template name")
    return path


@router.get("", response_class=HTMLResponse)
async def list_email_templates(request: Request, _=Depends(require_dashboard_auth)):
    template_files = []
    if os.path.isdir(MAIL_TEMPLATES_DIR):
        for f in sorted(os.listdir(MAIL_TEMPLATES_DIR)):
            if f.endswith(".html") and f != "base.html":
                template_files.append(f.replace(".html", ""))

    return templates.TemplateResponse(
        "email_editor/list.html",
        {"request": request, "template_files": template_files},
    )


@router.get("/{name}", response_class=HTMLResponse)
async def edit_email_template(
    name: str, request: Request, _=Depends(require_dashboard_auth)
):
    path = _validate_template_name(name)
    content = ""
    if os.path.isfile(path):
        with open(path) as f:
            content = f.read()

    return templates.TemplateResponse(
        "email_editor/edit.html",
        {"request": request, "name": name, "content": content},
    )


@router.post("/{name}")
async def save_email_template(
    name: str, request: Request, _=Depends(require_dashboard_auth)
):
    path = _validate_template_name(name)
    form = await request.form()
    content = form.get("content", "")
    with open(path, "w") as f:
        f.write(content)
    return HTMLResponse('<span class="text-success">Saved!</span>')
