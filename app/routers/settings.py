import csv
import io
import shutil
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.auth.service import hash_password, new_invite_token, verify_password
from app.config import settings
from app.deps import DB, AdminUser, CurrentUser, redirect, render
from app.models import Transaction, User
from app.util import cents_to_str

router = APIRouter()


def _backup_dir():
    d = settings.database_path.parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/more")
def more(request: Request, user: CurrentUser):
    return render(request, "settings/more.html")


@router.get("/settings")
def index(request: Request, db: DB, user: CurrentUser):
    users = db.scalars(select(User).order_by(User.id)).all()
    backups = sorted(p.name for p in _backup_dir().glob("*.db"))[-5:]
    base_url = str(request.base_url).rstrip("/")
    return render(request, "settings/index.html", users=users, backups=backups, base_url=base_url)


@router.post("/settings/users")
def invite(
    request: Request,
    db: DB,
    admin: AdminUser,
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
):
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return redirect("/settings", flash="That email already has an account.")
    db.add(User(email=email, display_name=display_name.strip(), invite_token=new_invite_token()))
    db.commit()
    return redirect("/settings", flash="Invite created. Send them the link below their name.")


@router.post("/settings/password")
def change_password(
    request: Request,
    db: DB,
    user: CurrentUser,
    current: Annotated[str, Form()],
    new: Annotated[str, Form()],
):
    if not verify_password(current, user.password_hash):
        return redirect("/settings", flash="Current password is wrong.")
    if len(new) < 8:
        return redirect("/settings", flash="New password must be 8+ characters.")
    user.password_hash = hash_password(new)
    db.commit()
    return redirect("/settings", flash="Password changed.")


@router.post("/settings/backup")
def backup(request: Request, db: DB, user: CurrentUser):
    db.execute(__import__("sqlalchemy").text("PRAGMA wal_checkpoint(TRUNCATE)"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = _backup_dir() / f"budget-{stamp}.db"
    shutil.copy2(settings.database_path, dest)
    return redirect("/settings", flash=f"Backed up to {dest.name}.")


@router.get("/settings/export.csv")
def export_csv(db: DB, user: CurrentUser):
    rows = db.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category),
            joinedload(Transaction.sub_budget),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    ).all()

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "date",
                "post_date",
                "account",
                "description",
                "merchant",
                "amount",
                "kind",
                "category",
                "sub_budget",
                "excluded",
                "notes",
                "bank_category",
                "card_holder",
            ]
        )
        yield buf.getvalue()
        for t in rows:
            buf.seek(0)
            buf.truncate()
            w.writerow(
                [
                    t.date,
                    t.post_date or "",
                    t.account.name,
                    t.description_raw,
                    t.merchant_name or "",
                    cents_to_str(t.amount, sign=True).replace(settings.currency_symbol, ""),
                    t.kind,
                    t.category.name if t.category else "",
                    t.sub_budget.name if t.sub_budget else "",
                    "yes" if t.is_excluded else "",
                    t.notes or "",
                    t.bank_category or "",
                    t.card_holder or "",
                ]
            )
            yield buf.getvalue()

    return StreamingResponse(
        gen(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
