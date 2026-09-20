from typing import Annotated

from fastapi import APIRouter, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.deps import DB, CurrentUser, redirect, render
from app.importer import service
from app.importer.parser import ParseError, sniff_headers
from app.models import Account, CsvProfile, Import

router = APIRouter(prefix="/import")


def _accounts(db):
    return db.scalars(
        select(Account)
        .options(joinedload(Account.csv_profile))
        .where(Account.is_archived.is_(False))
        .order_by(Account.name)
    ).all()


@router.get("")
def index(request: Request, db: DB, user: CurrentUser, error: str | None = None):
    recent = db.scalars(
        select(Import).options(joinedload(Import.account)).order_by(Import.id.desc()).limit(5)
    ).all()
    last = recent[0].account_id if recent else None
    return render(
        request,
        "import/index.html",
        accounts=_accounts(db),
        recent=recent,
        last_account_id=last,
        error=error,
    )


@router.post("/preview")
async def preview(
    request: Request,
    db: DB,
    user: CurrentUser,
    account_id: Annotated[int, Form()],
    file: UploadFile,
):
    account = db.get(Account, account_id)
    if not account:
        return redirect("/import", flash="Unknown account.")
    data = await file.read()
    try:
        staged = service.stage(db, account, file.filename or "upload.csv", data)
    except (ParseError, ValueError) as e:
        return render(
            request,
            "import/index.html",
            accounts=_accounts(db),
            recent=[],
            last_account_id=account_id,
            error=str(e),
        )
    return render(
        request, "import/preview.html", account=account, staged=staged, c=staged.classified
    )


@router.post("/commit")
async def commit(
    request: Request,
    db: DB,
    user: CurrentUser,
    account_id: Annotated[int, Form()],
    sha: Annotated[str, Form()],
    filename: Annotated[str, Form()],
):
    account = db.get(Account, account_id)
    if not account:
        return redirect("/import", flash="Unknown account.")
    form = await request.form()
    keep = {
        int(k.removeprefix("flag_"))
        for k, v in form.multi_items()
        if k.startswith("flag_") and v == "keep"
    }
    try:
        staged = service.restage(db, account, sha, filename)
    except ParseError as e:
        return redirect("/import", flash=str(e))
    imp = service.commit(db, account, user, staged, keep)
    return redirect(
        f"/review?import_id={imp.id}",
        flash=f"Imported {imp.rows_new} new transactions from {account.name}.",
    )


@router.get("/history")
def history(request: Request, db: DB, user: CurrentUser):
    imports = db.scalars(
        select(Import)
        .options(joinedload(Import.account), joinedload(Import.user))
        .order_by(Import.id.desc())
    ).all()
    return render(request, "import/history.html", imports=imports)


@router.post("/{import_id}/undo")
def undo(request: Request, db: DB, user: CurrentUser, import_id: int):
    imp = db.get(Import, import_id)
    if not imp or imp.undone_at:
        return redirect("/import/history", flash="Nothing to undo.")
    deleted, kept = service.undo(db, imp, user)
    msg = f"Removed {deleted} transactions."
    if kept:
        msg += f" Kept {kept} you had edited."
    return redirect("/import/history", flash=msg)


# --- CSV profiles ---------------------------------------------------------


@router.get("/profiles")
def profiles(request: Request, db: DB, user: CurrentUser):
    ps = db.scalars(select(CsvProfile).order_by(CsvProfile.is_builtin.desc(), CsvProfile.name))
    return render(request, "import/profiles.html", profiles=ps.all())


@router.get("/profiles/new")
def profile_new(request: Request, db: DB, user: CurrentUser):
    return render(request, "import/profile_form.html", profile=None, headers=None)


@router.post("/profiles/sample")
async def profile_sample(
    request: Request,
    db: DB,
    user: CurrentUser,
    file: UploadFile | None = None,
    headers: Annotated[str, Form()] = "",
    profile_id: Annotated[str, Form()] = "",
):
    profile = db.get(CsvProfile, int(profile_id)) if profile_id else None
    hdrs: list[str] = []
    if file is not None and file.filename:
        hdrs = sniff_headers(await file.read(), skip_rows=profile.skip_rows if profile else 0)
    elif headers.strip():
        hdrs = [h.strip() for h in headers.split(",") if h.strip()]
    if not hdrs:
        return render(
            request,
            "import/profile_form.html",
            profile=profile,
            headers=None,
            error="Upload a file or type the header names.",
        )
    return render(request, "import/profile_form.html", profile=profile, headers=hdrs)


def _profile_headers(p: CsvProfile) -> list[str]:
    cols = [
        p.col_date, p.col_post_date, p.col_description, p.col_merchant, p.col_amount,
        p.col_debit, p.col_credit, p.col_balance, p.col_reference, p.col_bank_category,
        p.col_bank_type, p.col_card_holder,
    ]  # fmt: skip
    return [c for c in cols if c]


@router.get("/profiles/{profile_id}")
def profile_edit(request: Request, db: DB, user: CurrentUser, profile_id: int):
    p = db.get(CsvProfile, profile_id)
    if not p:
        return redirect("/import/profiles")
    return render(request, "import/profile_form.html", profile=p, headers=_profile_headers(p))


@router.post("/profiles/{profile_id}")
async def profile_save(request: Request, db: DB, user: CurrentUser, profile_id: str):
    form = await request.form()
    if profile_id == "new":
        p = CsvProfile(col_date="", col_description="")
        db.add(p)
    else:
        existing = db.get(CsvProfile, int(profile_id))
        if not existing or existing.is_builtin:
            return redirect("/import/profiles", flash="Built-in profiles can't be edited.")
        p = existing
    p.name = str(form.get("name") or "Untitled").strip()
    for col in (
        "col_date", "col_post_date", "col_description", "col_merchant", "col_amount",
        "col_debit", "col_credit", "col_balance", "col_reference", "col_bank_category",
        "col_bank_type", "col_card_holder",
    ):  # fmt: skip
        setattr(p, col, str(form.get(col) or "").strip() or None)
    if not p.col_date or not p.col_description:
        return redirect("/import/profiles", flash="Date and description columns are required.")
    if not p.col_amount and not (p.col_debit or p.col_credit):
        return redirect("/import/profiles", flash="Pick an amount column or debit/credit columns.")
    p.date_format = str(form.get("date_format") or "%m/%d/%Y")
    p.positive_kind = str(form.get("positive_kind") or "expense")
    p.skip_rows = int(str(form.get("skip_rows") or 0))
    p.negate_amounts = bool(form.get("negate_amounts"))
    db.commit()
    return redirect("/import/profiles", flash="Profile saved.")


@router.post("/profiles/{profile_id}/delete")
def profile_delete(request: Request, db: DB, user: CurrentUser, profile_id: int):
    p = db.get(CsvProfile, profile_id)
    if p and not p.is_builtin:
        in_use = db.scalar(select(Account.id).where(Account.csv_profile_id == p.id).limit(1))
        if in_use:
            return redirect("/import/profiles", flash="An account uses this profile.")
        db.delete(p)
        db.commit()
    return redirect("/import/profiles", flash="Deleted.")
