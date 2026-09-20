import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.audit import log, new_batch
from app.deps import DB, CurrentUser, redirect, render, templates
from app.models import Account, AuditLog, Category, SubBudget, Transaction
from app.queries import SHOW_OPTIONS, TxnFilter, txn_select
from app.util import clean_description, shift_month, str_to_cents, this_month

router = APIRouter(prefix="/transactions")

PAGE = 250


def _lookups(db):
    cats = db.scalars(
        select(Category)
        .where(Category.is_archived.is_(False))
        .order_by(Category.group_name, Category.sort_order, Category.name)
    ).all()
    accounts = db.scalars(select(Account).order_by(Account.name)).all()
    subs = db.scalars(
        select(SubBudget).where(SubBudget.status == "active").order_by(SubBudget.name)
    ).all()
    holders = [
        h
        for (h,) in db.execute(
            select(Transaction.card_holder).where(Transaction.card_holder.isnot(None)).distinct()
        )
    ]
    return cats, accounts, subs, holders


def _snapshot(t: Transaction) -> dict:
    return {
        "category_id": t.category_id,
        "category_locked": t.category_locked,
        "sub_budget_id": t.sub_budget_id,
        "is_excluded": t.is_excluded,
        "kind": t.kind,
        "notes": t.notes,
        "merchant_name": t.merchant_name,
    }


@router.get("")
def list_txns(request: Request, db: DB, user: CurrentUser):
    p = request.query_params
    f = TxnFilter.from_params(p)
    if "month" not in p:
        f.month = this_month()
    page = int(p.get("page") or 1)
    sub = f.apply(select(Transaction.id, Transaction.amount)).subquery()
    total, total_amount = db.execute(select(func.count(), func.sum(sub.c.amount))).one()
    rows = db.scalars(
        f.apply(txn_select())
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * PAGE)
        .limit(PAGE)
    ).all()
    cats, accounts, subs, holders = _lookups(db)
    return render(
        request,
        "transactions/list.html",
        rows=rows,
        f=f,
        params=f.as_params(),
        total=total or 0,
        total_amount=total_amount or 0,
        page=page,
        pages=max(1, -(-total // PAGE)),
        cats=cats,
        accounts=accounts,
        subs=subs,
        holders=holders,
        show_options=SHOW_OPTIONS,
        prev_month=shift_month(f.month, -1) if f.month else None,
        next_month=shift_month(f.month, 1) if f.month else None,
    )


@router.get("/new")
def new_form(request: Request, db: DB, user: CurrentUser):
    cats, accounts, subs, _ = _lookups(db)
    return render(
        request,
        "transactions/form.html",
        t=None,
        cats=cats,
        accounts=accounts,
        subs=subs,
        today=dt.date.today().isoformat(),
    )


@router.post("/new")
def create(
    request: Request,
    db: DB,
    user: CurrentUser,
    account_id: Annotated[int, Form()],
    date: Annotated[dt.date, Form()],
    description: Annotated[str, Form()],
    amount: Annotated[str, Form()],
    kind: Annotated[str, Form()] = "expense",
    category_id: Annotated[str, Form()] = "",
    sub_budget_id: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    is_excluded: Annotated[str | None, Form()] = None,
):
    cents = abs(str_to_cents(amount))
    t = Transaction(
        account_id=account_id,
        date=date,
        description_raw=description.strip(),
        description_clean=clean_description(description),
        merchant_name=description.strip(),
        amount=-cents if kind == "expense" else cents,
        kind=kind,
        category_id=int(category_id) if category_id else None,
        category_locked=bool(category_id),
        sub_budget_id=int(sub_budget_id) if sub_budget_id else None,
        is_excluded=bool(is_excluded),
        notes=notes.strip() or None,
        source="manual",
        created_by=user.id,
    )
    db.add(t)
    db.flush()
    log(db, user.id, "transaction", t.id, "create", after=_snapshot(t))
    db.commit()
    return redirect(f"/transactions?month={date.strftime('%Y-%m')}&show=all", flash="Added.")


# --- bulk -----------------------------------------------------------------


@router.post("/bulk")
async def bulk(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    action = str(form.get("action") or "")
    value = str(form.get("value") or "")
    f = TxnFilter.from_params(form)
    back = "/transactions?" + "&".join(f"{k}={v}" for k, v in f.as_params().items())
    if form.get("all") == "1":
        txns = db.scalars(f.apply(select(Transaction))).all()
    else:
        ids = [int(str(x)) for x in form.getlist("ids") if str(x).isdigit()]
        txns = db.scalars(select(Transaction).where(Transaction.id.in_(ids))).all() if ids else []
    if not txns:
        return redirect(back, flash="Nothing selected.")
    batch = new_batch()
    n = 0
    for t in txns:
        before = _snapshot(t)
        if action == "category":
            t.category_id = int(value) if value else None
            t.category_locked = t.category_id is not None
        elif action == "exclude":
            t.is_excluded = True
        elif action == "include":
            t.is_excluded = False
        elif action == "transfer":
            t.kind = "transfer"
            t.is_excluded = True
        elif action == "expense":
            t.kind = "expense"
            t.is_excluded = False
        elif action == "sub_budget":
            t.sub_budget_id = int(value) if value else None
        elif action == "delete":
            log(db, user.id, "transaction", t.id, "delete", before=before, batch_id=batch)
            db.delete(t)
            n += 1
            continue
        else:
            return redirect(back, flash="Unknown action.")
        after = _snapshot(t)
        if after != before:
            log(
                db,
                user.id,
                "transaction",
                t.id,
                "update",
                before=before,
                after=after,
                batch_id=batch,
            )
            n += 1
    db.commit()
    verb = {"delete": "Deleted", "exclude": "Excluded", "include": "Included"}.get(
        action, "Updated"
    )
    flash = f"{verb} {n} of {len(txns)}."
    if action != "delete" and n:
        flash += f' <a href="#" onclick="bulkUndo(\'{batch}\');return false">Undo</a>'
    return redirect(back, flash=flash)


@router.post("/bulk/undo/{batch_id}")
def bulk_undo(request: Request, db: DB, user: CurrentUser, batch_id: str):
    import json

    entries = db.scalars(
        select(AuditLog).where(AuditLog.batch_id == batch_id, AuditLog.action == "update")
    ).all()
    n = 0
    for e in entries:
        t = db.get(Transaction, e.entity_id) if e.entity_id else None
        if not t or not e.before_json:
            continue
        for k, v in json.loads(e.before_json).items():
            setattr(t, k, v)
        n += 1
    log(db, user.id, "transaction", None, "bulk_undo", after={"batch": batch_id, "n": n})
    db.commit()
    return redirect(request.headers.get("referer") or "/transactions", flash=f"Undid {n} changes.")


@router.get("/{txn_id}")
def edit_form(request: Request, db: DB, user: CurrentUser, txn_id: int):
    t = db.scalar(txn_select().where(Transaction.id == txn_id))
    if not t:
        return redirect("/transactions")
    cats, accounts, subs, _ = _lookups(db)
    history = db.scalars(
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .where(AuditLog.entity == "transaction", AuditLog.entity_id == t.id)
        .order_by(AuditLog.id.desc())
        .limit(10)
    ).all()
    return render(
        request,
        "transactions/form.html",
        t=t,
        cats=cats,
        accounts=accounts,
        subs=subs,
        history=history,
        today=None,
    )


@router.post("/{txn_id}")
def update(
    request: Request,
    db: DB,
    user: CurrentUser,
    txn_id: int,
    date: Annotated[dt.date, Form()],
    description: Annotated[str, Form()],
    amount: Annotated[str, Form()],
    kind: Annotated[str, Form()] = "expense",
    category_id: Annotated[str, Form()] = "",
    sub_budget_id: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    is_excluded: Annotated[str | None, Form()] = None,
):
    t = db.get(Transaction, txn_id)
    if not t:
        return redirect("/transactions")
    before = _snapshot(t)
    t.date = date
    if t.source == "manual":
        t.description_raw = description.strip()
        t.description_clean = clean_description(description)
    t.merchant_name = description.strip() or None
    cents = abs(str_to_cents(amount))
    t.amount = -cents if kind == "expense" else cents
    t.kind = kind
    new_cat = int(category_id) if category_id else None
    if new_cat != t.category_id:
        t.category_locked = new_cat is not None
    t.category_id = new_cat
    t.sub_budget_id = int(sub_budget_id) if sub_budget_id else None
    t.is_excluded = bool(is_excluded)
    t.notes = notes.strip() or None
    log(db, user.id, "transaction", t.id, "update", before=before, after=_snapshot(t))
    db.commit()
    back = request.query_params.get("back") or f"/transactions?month={date.strftime('%Y-%m')}"
    return redirect(back, flash="Saved.")


@router.post("/{txn_id}/delete")
def delete(request: Request, db: DB, user: CurrentUser, txn_id: int):
    t = db.get(Transaction, txn_id)
    if t:
        log(db, user.id, "transaction", t.id, "delete", before=_snapshot(t))
        month = t.date.strftime("%Y-%m")
        db.delete(t)
        db.commit()
        return redirect(f"/transactions?month={month}", flash="Deleted.")
    return redirect("/transactions")


@router.post("/{txn_id}/category")
def set_category(
    request: Request,
    db: DB,
    user: CurrentUser,
    txn_id: int,
    category_id: Annotated[str, Form()] = "",
):
    """HTMX: change one row's category from the chip. Returns the row."""
    t = db.scalar(txn_select().where(Transaction.id == txn_id))
    if not t:
        return redirect("/transactions")
    before = _snapshot(t)
    if category_id == "exclude":
        t.is_excluded = True
    elif category_id == "transfer":
        t.kind = "transfer"
        t.is_excluded = True
    else:
        t.category_id = int(category_id) if category_id else None
        t.category_locked = t.category_id is not None
    log(db, user.id, "transaction", t.id, "update", before=before, after=_snapshot(t))
    db.commit()
    db.refresh(t)
    return templates.TemplateResponse(
        request, "partials/txn_row.html", {"t": t, "user": user, "show_day": False}
    )
