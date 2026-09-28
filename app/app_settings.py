"""Settings stored in the database and edited from the Settings page."""

import datetime as dt

from sqlalchemy.orm import Session

from app.models import AppSetting

TRACKING_START = "tracking_start"
DEFAULT_TRACKING_START = "2026-08-01"


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def tracking_start(db: Session) -> dt.date:
    """Transactions dated before this are never imported and stay excluded."""
    return dt.date.fromisoformat(get_setting(db, TRACKING_START, DEFAULT_TRACKING_START))
