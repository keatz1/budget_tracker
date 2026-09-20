"""FastAPI dependencies: db session, current user, templates."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE, read_session_token, user_count
from app.config import settings
from app.db import get_db
from app.models import User
from app.util import cents_to_str, month_label

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["money"] = cents_to_str
templates.env.filters["month_label"] = month_label
templates.env.globals["currency"] = settings.currency_symbol


class NeedsLogin(HTTPException):
    def __init__(self, target: str) -> None:
        super().__init__(status_code=303, headers={"Location": target})


def optional_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User | None:
    uid = read_session_token(request.cookies.get(SESSION_COOKIE))
    user = db.get(User, uid) if uid else None
    request.state.user = user
    return user


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User | None, Depends(optional_user)],
) -> User:
    if user is None:
        if user_count(db) == 0:
            raise NeedsLogin("/setup")
        if request.headers.get("HX-Request"):
            raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
        raise NeedsLogin("/login")
    return user


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(admin_user)]


def render(request: Request, name: str, **ctx) -> object:
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("flash", request.cookies.get("bt_flash"))
    return templates.TemplateResponse(request, name, ctx)


def redirect(url: str, flash: str | None = None, hx: Request | None = None) -> RedirectResponse:
    """303 redirect, or an HX-Redirect for HTMX requests."""
    if hx is not None and hx.headers.get("HX-Request"):
        resp = RedirectResponse(url, status_code=204)
        resp.headers["HX-Redirect"] = url
    else:
        resp = RedirectResponse(url, status_code=303)
    if flash:
        resp.set_cookie("bt_flash", flash, max_age=10, httponly=True, samesite="lax")
    return resp
