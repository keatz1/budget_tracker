"""Work out which CSV layout a file has and which account it belongs to."""

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, CsvProfile


def _declared(p: CsvProfile) -> list[str]:
    cols = [
        p.col_date, p.col_post_date, p.col_description, p.col_merchant, p.col_amount,
        p.col_debit, p.col_credit, p.col_balance, p.col_reference, p.col_bank_category,
        p.col_bank_type, p.col_card_holder,
    ]  # fmt: skip
    return [c for c in cols if c]


def _required(p: CsvProfile) -> list[str]:
    req = [p.col_date, p.col_description]
    if p.col_amount:
        req.append(p.col_amount)
    else:
        req += [c for c in (p.col_debit, p.col_credit) if c]
    return [c for c in req if c]


def detect_profile(db: Session, headers: list[str]) -> CsvProfile | None:
    """The profile whose declared columns best match the file's headers.
    Every required column must be present; ties go to the profile that declares more."""
    hs = {h.strip() for h in headers}
    best: tuple[int, int, CsvProfile] | None = None
    for p in db.scalars(select(CsvProfile)):
        if not all(c in hs for c in _required(p)):
            continue
        declared = _declared(p)
        score = sum(1 for c in declared if c in hs)
        key = (score, len(declared))
        if best is None or key > (best[0], best[1]):
            best = (score, len(declared), p)
    return best[2] if best else None


@dataclass
class AccountMatch:
    account: Account | None
    candidates: list[Account] = field(default_factory=list)
    hint_from_filename: str | None = None


def filename_digits(filename: str) -> str | None:
    """A 4-digit group in the file name, like the 8393 in Chase8393_Activity.csv.
    Digits glued to a word win; a bare year like 2026 is ignored."""
    attached = re.search(r"[A-Za-z]{2,}(\d{4})(?!\d)", filename)
    if attached:
        return attached.group(1)
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", filename):
        if not 1900 <= int(m.group(1)) <= 2099:
            return m.group(1)
    return None


def detect_account(db: Session, profile: CsvProfile, filename: str) -> AccountMatch:
    candidates = list(
        db.scalars(
            select(Account)
            .where(Account.csv_profile_id == profile.id, Account.is_archived.is_(False))
            .order_by(Account.name)
        )
    )
    hint = filename_digits(filename)
    if len(candidates) == 1:
        return AccountMatch(candidates[0], candidates, hint)
    lowered = filename.lower()
    hinted = [a for a in candidates if a.import_hint and a.import_hint.lower() in lowered]
    if len(hinted) == 1:
        return AccountMatch(hinted[0], candidates, hint)
    return AccountMatch(None, candidates, hint)
