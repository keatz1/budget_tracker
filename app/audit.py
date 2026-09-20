import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def new_batch() -> str:
    return str(uuid.uuid4())


def log(
    db: Session,
    user_id: int | None,
    entity: str,
    entity_id: int | None,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    batch_id: str | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            before_json=json.dumps(before, default=str) if before is not None else None,
            after_json=json.dumps(after, default=str) if after is not None else None,
            batch_id=batch_id,
        )
    )
