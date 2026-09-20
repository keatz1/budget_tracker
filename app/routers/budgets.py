from fastapi import APIRouter, Request
from sqlalchemy import select

from app.budgets.service import month_summary
from app.deps import DB, CurrentUser, redirect, render
from app.models import Budget, Category
from app.util import shift_month, str_to_cents, this_month

router = APIRouter(prefix="/budgets")


@router.get("")
def index(request: Request, db: DB, user: CurrentUser, month: str | None = None):
    month = month or this_month()
    s = month_summary(db, month)
    overrides = {
        b.category_id: b.amount for b in db.scalars(select(Budget).where(Budget.month == month))
    }
    last = shift_month(month, -1)
    last_overrides = db.scalar(select(Budget.id).where(Budget.month == last).limit(1)) is not None
    return render(
        request,
        "budgets/index.html",
        month=month,
        prev_month=last,
        next_month=shift_month(month, 1),
        s=s,
        overrides=overrides,
        last_overrides=last_overrides,
    )


@router.post("")
async def save(request: Request, db: DB, user: CurrentUser, month: str):
    form = await request.form()
    cats = {c.id: c for c in db.scalars(select(Category)).all()}
    existing = {b.category_id: b for b in db.scalars(select(Budget).where(Budget.month == month))}
    for key, raw in form.multi_items():
        val = str(raw).strip()
        if key.startswith("default_"):
            cid = int(key.removeprefix("default_"))
            if cid in cats:
                cats[cid].default_budget = abs(str_to_cents(val)) if val else 0
        elif key.startswith("month_"):
            cid = int(key.removeprefix("month_"))
            if cid not in cats:
                continue
            if val:
                amt = abs(str_to_cents(val))
                if cid in existing:
                    existing[cid].amount = amt
                else:
                    db.add(Budget(category_id=cid, month=month, amount=amt))
            elif cid in existing:
                db.delete(existing[cid])
    db.commit()
    return redirect(f"/budgets?month={month}", flash="Budgets saved.")


@router.post("/copy-last")
def copy_last(request: Request, db: DB, user: CurrentUser, month: str):
    last = shift_month(month, -1)
    have = {b.category_id for b in db.scalars(select(Budget).where(Budget.month == month))}
    n = 0
    for b in db.scalars(select(Budget).where(Budget.month == last)):
        if b.category_id not in have:
            db.add(Budget(category_id=b.category_id, month=month, amount=b.amount))
            n += 1
    db.commit()
    return redirect(f"/budgets?month={month}", flash=f"Copied {n} overrides from {last}.")
