from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth.service import (
    SESSION_COOKIE,
    authenticate,
    hash_password,
    make_session_token,
    user_count,
)
from app.config import settings
from app.deps import DB, optional_user, redirect, render
from app.models import User

router = APIRouter()


def _login_response(user: User, target: str = "/") -> RedirectResponse:
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        make_session_token(user.id),
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/setup")
def setup_form(request: Request, db: DB):
    if user_count(db):
        return redirect("/login")
    return render(request, "auth/setup.html")


@router.post("/setup")
def setup_submit(
    request: Request,
    db: DB,
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    if user_count(db):
        return redirect("/login")
    if len(password) < 8:
        return render(request, "auth/setup.html", error="Password must be 8+ characters.")
    user = User(
        email=email.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    return _login_response(user, "/accounts")


@router.get("/login")
def login_form(request: Request, db: DB, user: Annotated[User | None, Depends(optional_user)]):
    if user:
        return redirect("/")
    if user_count(db) == 0:
        return redirect("/setup")
    return render(request, "auth/login.html")


@router.post("/login")
def login_submit(
    request: Request, db: DB, email: Annotated[str, Form()], password: Annotated[str, Form()]
):
    user = authenticate(db, email, password)
    if not user:
        return render(request, "auth/login.html", error="Wrong email or password.")
    return _login_response(user)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/invite/{token}")
def invite_form(request: Request, db: DB, token: str):
    invitee = db.scalar(select(User).where(User.invite_token == token))
    if not invitee or invitee.password_hash:
        return render(request, "auth/login.html", error="That invite link is no longer valid.")
    return render(request, "auth/invite.html", invitee=invitee)


@router.post("/invite/{token}")
def invite_submit(
    request: Request,
    db: DB,
    token: str,
    password: Annotated[str, Form()],
    password2: Annotated[str, Form()],
):
    invitee = db.scalar(select(User).where(User.invite_token == token))
    if not invitee or invitee.password_hash:
        return render(request, "auth/login.html", error="That invite link is no longer valid.")
    if password != password2:
        return render(request, "auth/invite.html", invitee=invitee, error="Passwords don't match.")
    if len(password) < 8:
        return render(request, "auth/invite.html", invitee=invitee, error="8+ characters, please.")
    invitee.password_hash = hash_password(password)
    invitee.invite_token = None
    db.commit()
    return _login_response(invitee)
