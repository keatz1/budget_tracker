"""Fingerprints and the three-bucket split: new / duplicate / flagged."""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importer.parser import ParsedRow
from app.models import Transaction

FLAG_WINDOW_DAYS = 3


def _identity(row: ParsedRow) -> tuple:
    return (
        row.date.isoformat(),
        row.post_date.isoformat() if row.post_date else "",
        row.amount,
        row.description_clean,
        row.balance if row.balance is not None else "",
    )


def fingerprint(account_id: int, row: ParsedRow, n: int) -> str:
    key = "|".join(str(p) for p in (account_id, *_identity(row), n))
    return hashlib.sha256(key.encode()).hexdigest()


def assign_fingerprints(account_id: int, rows: list[ParsedRow]) -> None:
    """Identical rows on the same day get n = 0, 1, 2... in file order."""
    seen: Counter[tuple] = Counter()
    for row in rows:
        ident = _identity(row)
        row.dup_index = seen[ident]
        seen[ident] += 1
        row.fingerprint = fingerprint(account_id, row, row.dup_index)


@dataclass
class FlaggedPair:
    row: ParsedRow
    existing: Transaction


@dataclass
class Classified:
    new: list[ParsedRow] = field(default_factory=list)
    duplicate: list[ParsedRow] = field(default_factory=list)
    flagged: list[FlaggedPair] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.new) + len(self.duplicate) + len(self.flagged)


def classify(db: Session, account_id: int, rows: list[ParsedRow]) -> Classified:
    assign_fingerprints(account_id, rows)
    if not rows:
        return Classified()
    fps = {r.fingerprint for r in rows}
    existing_fps = set(
        db.scalars(
            select(Transaction.fingerprint).where(
                Transaction.account_id == account_id, Transaction.fingerprint.in_(fps)
            )
        )
    )
    lo = min(r.date for r in rows) - timedelta(days=FLAG_WINDOW_DAYS)
    hi = max(r.date for r in rows) + timedelta(days=FLAG_WINDOW_DAYS)
    # Candidates for "pending -> posted" flags: existing rows in the window that
    # are NOT already accounted for by an exact duplicate in this file.
    candidates = [
        t
        for t in db.scalars(
            select(Transaction).where(
                Transaction.account_id == account_id,
                Transaction.source == "import",
                Transaction.date >= lo,
                Transaction.date <= hi,
            )
        )
        if t.fingerprint not in fps
    ]
    by_amount: dict[int, list[Transaction]] = {}
    for t in candidates:
        by_amount.setdefault(t.amount, []).append(t)

    result = Classified()
    claimed: set[int] = set()
    for row in rows:
        if row.fingerprint in existing_fps:
            result.duplicate.append(row)
            continue
        match = None
        for t in by_amount.get(row.amount, []):
            if t.id in claimed or t.description_clean == row.description_clean:
                continue
            if abs((t.date - row.date).days) <= FLAG_WINDOW_DAYS:
                match = t
                break
        if match is not None:
            claimed.add(match.id)
            result.flagged.append(FlaggedPair(row=row, existing=match))
        else:
            result.new.append(row)
    return result
