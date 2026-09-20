from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select

from app.deps import DB, CurrentUser, redirect, render
from app.models import Account, CsvProfile, Transaction

router = APIRouter(prefix="/accounts")


@router.get("")
def list_accounts(request: Request, db: DB, user: CurrentUser):
    accounts = db.scalars(select(Account).order_by(Account.is_archived, Account.name)).all()
    counts: dict[int, int] = {
        aid: n
        for aid, n in db.execute(
            select(Transaction.account_id, func.count()).group_by(Transaction.account_id)
        )
    }
    return render(request, "accounts/list.html", accounts=accounts, counts=counts)


def _profiles(db):
    return db.scalars(select(CsvProfile).order_by(CsvProfile.name)).all()


@router.get("/new")
def new_form(request: Request, db: DB, user: CurrentUser):
    return render(request, "accounts/form.html", account=None, profiles=_profiles(db))


@router.post("/new")
def create(
    request: Request,
    db: DB,
    user: CurrentUser,
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    institution: Annotated[str, Form()] = "",
    csv_profile_id: Annotated[str, Form()] = "",
):
    acct = Account(
        name=name.strip(),
        institution=institution.strip() or None,
        kind=kind,
        csv_profile_id=int(csv_profile_id) if csv_profile_id else None,
    )
    db.add(acct)
    db.commit()
    return redirect("/accounts", flash=f"Added {acct.name}.")


@router.get("/{account_id}")
def edit_form(request: Request, db: DB, user: CurrentUser, account_id: int):
    acct = db.get(Account, account_id)
    if not acct:
        return redirect("/accounts")
    has_txns = db.scalar(select(Transaction.id).where(Transaction.account_id == acct.id).limit(1))
    return render(
        request,
        "accounts/form.html",
        account=acct,
        profiles=_profiles(db),
        has_txns=has_txns is not None,
    )


@router.post("/{account_id}")
def update(
    request: Request,
    db: DB,
    user: CurrentUser,
    account_id: int,
    name: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    institution: Annotated[str, Form()] = "",
    csv_profile_id: Annotated[str, Form()] = "",
    is_archived: Annotated[str | None, Form()] = None,
):
    acct = db.get(Account, account_id)
    if not acct:
        return redirect("/accounts")
    acct.name = name.strip()
    acct.institution = institution.strip() or None
    acct.kind = kind
    acct.csv_profile_id = int(csv_profile_id) if csv_profile_id else None
    acct.is_archived = bool(is_archived)
    db.commit()
    return redirect("/accounts", flash="Saved.")


@router.post("/{account_id}/delete")
def delete(request: Request, db: DB, user: CurrentUser, account_id: int):
    acct = db.get(Account, account_id)
    if acct:
        has = db.scalar(select(Transaction.id).where(Transaction.account_id == acct.id).limit(1))
        if has:
            return redirect(
                f"/accounts/{account_id}", flash="Account has transactions; archive it."
            )
        db.delete(acct)
        db.commit()
    return redirect("/accounts", flash="Deleted.")
