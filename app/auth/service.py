import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User

_hasher = PasswordHasher()
_signer = URLSafeTimedSerializer(settings.secret_key, salt="session")

SESSION_COOKIE = "bt_session"


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, pw_hash: str | None) -> bool:
    if not pw_hash:
        return False
    try:
        return _hasher.verify(pw_hash, pw)
    except VerifyMismatchError:
        return False


def make_session_token(user_id: int) -> str:
    return _signer.dumps({"uid": user_id})


def read_session_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        data = _signer.loads(token, max_age=settings.session_days * 86400)
    except BadSignature:
        return None
    return data.get("uid")


def new_invite_token() -> str:
    return secrets.token_urlsafe(24)


def user_count(db: Session) -> int:
    return db.scalar(select(func.count(User.id))) or 0


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user and verify_password(password, user.password_hash):
        return user
    return None
