"""Stage an upload, preview it, commit it, undo it."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.app_settings import tracking_start
from app.audit import log
from app.config import settings
from app.importer.dedupe import Classified, classify
from app.importer.detect import AccountMatch, detect_account, detect_profile
from app.importer.parser import ParsedRow, ParseError, parse_csv, sniff_headers
from app.models import Account, CsvProfile, Import, Rule, Transaction, User
from app.models.base import utcnow
from app.rules.engine import first_match, load_rules


@dataclass
class Staged:
    sha: str
    filename: str
    path: Path
    rows: list[ParsedRow]
    classified: Classified
    already_imported: Import | None
    predictions: dict[int, Rule | None]  # row.index -> rule that would fire
    skipped_old: int = 0  # rows dated before the tracking start
    profile: CsvProfile | None = None
    match: AccountMatch | None = None
    account: Account | None = None
    error: str | None = None
    index: int = 0


def _staging_path(sha: str) -> Path:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir / f"{sha}.csv"


def _empty(sha: str, filename: str, path: Path, error: str, index: int = 0) -> Staged:
    return Staged(sha, filename, path, [], Classified(), None, {}, error=error, index=index)


def detect(db: Session, filename: str, data: bytes, index: int = 0) -> Staged:
    """Recognise the layout and the account from the file alone, then stage it."""
    sha = hashlib.sha256(data).hexdigest()
    path = _staging_path(sha)
    path.write_bytes(data)
    headers = sniff_headers(data)
    profile = detect_profile(db, headers)
    if profile is None:
        return _empty(
            sha, filename, path,
            f"Didn't recognise the columns in {filename}: {', '.join(headers[:8])}. "
            "Add a CSV profile for this bank under Import → CSV profiles.",
            index,
        )  # fmt: skip
    match = detect_account(db, profile, filename)
    if not match.candidates:
        return _empty(
            sha, filename, path,
            f"{filename} looks like a {profile.name} export, but no account uses that layout. "
            "Add the account first and pick that profile.",
            index,
        )  # fmt: skip
    account = match.account or match.candidates[0]
    st = stage(db, account, filename, data, profile=profile)
    st.profile, st.match, st.account, st.index = profile, match, account, index
    return st


def stage(
    db: Session, account: Account, filename: str, data: bytes, profile: CsvProfile | None = None
) -> Staged:
    profile = profile or account.csv_profile
    if profile is None:
        raise ParseError(f"{account.name} has no CSV profile. Set one on the account first.")
    sha = hashlib.sha256(data).hexdigest()
    path = _staging_path(sha)
    path.write_bytes(data)
    rows = parse_csv(data, profile)
    start = tracking_start(db)
    kept = [r for r in rows if r.date >= start]
    skipped_old = len(rows) - len(kept)
    classified = classify(db, account.id, kept)
    prior = db.scalar(
        select(Import).where(
            Import.account_id == account.id,
            Import.file_sha256 == sha,
            Import.undone_at.is_(None),
        )
    )
    rules = load_rules(db)
    predictions = {
        r.index: first_match(rules, _to_txn(account.id, r))
        for r in classified.new + [f.row for f in classified.flagged]
    }
    st = Staged(sha, filename, path, kept, classified, prior, predictions, skipped_old)
    st.account, st.profile = account, profile
    return st


def restage(db: Session, account: Account, sha: str, filename: str) -> Staged:
    path = _staging_path(sha)
    if not path.exists():
        raise ParseError("The uploaded file has gone. Please upload it again.")
    data = path.read_bytes()
    profile = detect_profile(db, sniff_headers(data)) or account.csv_profile
    return stage(db, account, filename, data, profile=profile)


def _to_txn(account_id: int, r: ParsedRow) -> Transaction:
    return Transaction(
        account_id=account_id,
        date=r.date,
        post_date=r.post_date,
        description_raw=r.description_raw,
        description_clean=r.description_clean,
        merchant_name=r.merchant_name,
        amount=r.amount,
        kind=r.kind,
        bank_category=r.bank_category,
        bank_type=r.bank_type,
        card_holder=r.card_holder,
        fingerprint=r.fingerprint,
        source="import",
    )


def commit(
    db: Session, account: Account, user: User, staged: Staged, keep_flagged: set[int]
) -> Import:
    """Insert new rows plus the flagged rows the user chose to keep. Run rules."""
    from app.rules.engine import apply_rules

    imp = Import(
        account_id=account.id,
        user_id=user.id,
        filename=staged.filename,
        file_sha256=staged.sha,
        rows_total=staged.classified.total + staged.skipped_old,
        rows_duplicate=len(staged.classified.duplicate),
        rows_flagged=len(staged.classified.flagged),
        rows_skipped_old=staged.skipped_old,
    )
    db.add(imp)
    db.flush()
    to_insert = list(staged.classified.new) + [
        f.row for f in staged.classified.flagged if f.row.index in keep_flagged
    ]
    txns = []
    for r in to_insert:
        t = _to_txn(account.id, r)
        t.import_id = imp.id
        t.created_by = user.id
        db.add(t)
        txns.append(t)
    apply_rules(db, txns)
    imp.rows_new = len(txns)
    log(db, user.id, "import", imp.id, "commit", after={"rows_new": imp.rows_new})
    db.commit()
    staged.path.unlink(missing_ok=True)
    return imp


def undo(db: Session, imp: Import, user: User) -> tuple[int, int]:
    """Delete the import's transactions. Edited ones (category set by hand,
    notes, exclusion) are kept and detached. Returns (deleted, kept)."""
    txns = db.scalars(select(Transaction).where(Transaction.import_id == imp.id)).all()
    deleted = kept = 0
    for t in txns:
        if t.category_locked or t.notes or t.sub_budget_id:
            t.import_id = None
            kept += 1
        else:
            db.delete(t)
            deleted += 1
    imp.undone_at = utcnow()
    log(db, user.id, "import", imp.id, "undo", after={"deleted": deleted, "kept": kept})
    db.commit()
    return deleted, kept


__all__ = ["Staged", "detect", "stage", "restage", "commit", "undo", "field"]
