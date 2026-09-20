import datetime as dt
import json

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.budgets.service import SubBudgetState, sub_budget_cumulative, sub_budget_states
from app.deps import DB, CurrentUser, redirect, render
from app.models import Category, SubBudget, Transaction
from app.queries import txn_select
from app.util import str_to_cents

router = APIRouter(prefix="/sub-budgets")


def _cats(db):
    return db.scalars(
        select(Category)
        .where(Category.is_archived.is_(False), Category.kind == "expense")
        .order_by(Category.group_name, Category.name)
    ).all()


@router.get("")
def list_subs(request: Request, db: DB, user: CurrentUser):
    active = sub_budget_states(db, "active")
    closed = sub_budget_states(db, "closed")
    return render(request, "sub_budgets/list.html", active=active, closed=closed)


@router.get("/new")
def new_form(request: Request, db: DB, user: CurrentUser):
    return render(
        request, "sub_budgets/form.html", sb=None, cats=_cats(db), today=dt.date.today().isoformat()
    )


def _apply(sb: SubBudget, form) -> str | None:
    name = str(form.get("name") or "").strip()
    if not name:
        return "Name is required."
    sb.name = name
    sb.category_id = int(str(form.get("category_id")))
    sb.total_amount = abs(str_to_cents(str(form.get("total_amount") or "0")))
    sb.start_date = dt.date.fromisoformat(str(form.get("start_date")))
    end = str(form.get("end_date") or "").strip()
    sb.end_date = dt.date.fromisoformat(end) if end else None
    sb.notes = str(form.get("notes") or "").strip() or None
    return None


@router.post("/new")
async def create(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    sb = SubBudget()
    err = _apply(sb, form)
    if err:
        return render(request, "sub_budgets/form.html", sb=None, cats=_cats(db), error=err,
                      today=dt.date.today().isoformat())  # fmt: skip
    db.add(sb)
    db.commit()
    return redirect(f"/sub-budgets/{sb.id}", flash="Sub-budget created. Assign transactions to it "
                    "from the transactions page (bulk edit) or with a rule.")  # fmt: skip


@router.get("/{sb_id}")
def detail(request: Request, db: DB, user: CurrentUser, sb_id: int):
    sb = db.get(SubBudget, sb_id)
    if not sb:
        return redirect("/sub-budgets")
    state = next((s for s in sub_budget_states(db, None) if s.sub.id == sb.id), None)
    state = state or SubBudgetState(sub=sb, spent=0, count=0)
    txns = db.scalars(
        txn_select()
        .where(Transaction.sub_budget_id == sb.id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    ).all()
    points = sub_budget_cumulative(db, sb)
    return render(
        request,
        "sub_budgets/detail.html",
        sb=sb,
        st=state,
        txns=txns,
        chart=json.dumps(
            {
                "points": points,
                "total": sb.total_amount,
                "end": sb.end_date.isoformat() if sb.end_date else None,
            }
        ),  # fmt: skip
    )


@router.get("/{sb_id}/edit")
def edit_form(request: Request, db: DB, user: CurrentUser, sb_id: int):
    sb = db.get(SubBudget, sb_id)
    if not sb:
        return redirect("/sub-budgets")
    return render(request, "sub_budgets/form.html", sb=sb, cats=_cats(db), today=None)


@router.post("/{sb_id}/edit")
async def update(request: Request, db: DB, user: CurrentUser, sb_id: int):
    sb = db.get(SubBudget, sb_id)
    if not sb:
        return redirect("/sub-budgets")
    form = await request.form()
    err = _apply(sb, form)
    if err:
        return render(
            request, "sub_budgets/form.html", sb=sb, cats=_cats(db), error=err, today=None
        )
    db.commit()
    return redirect(f"/sub-budgets/{sb.id}", flash="Saved.")


@router.post("/{sb_id}/toggle")
def toggle(request: Request, db: DB, user: CurrentUser, sb_id: int):
    sb = db.get(SubBudget, sb_id)
    if sb:
        sb.status = "closed" if sb.status == "active" else "active"
        db.commit()
    return redirect(f"/sub-budgets/{sb_id}")


@router.post("/{sb_id}/delete")
def delete(request: Request, db: DB, user: CurrentUser, sb_id: int):
    sb = db.get(SubBudget, sb_id)
    if sb:
        db.delete(sb)  # transactions keep their category; sub_budget_id is set NULL by the FK
        db.commit()
    return redirect("/sub-budgets", flash="Deleted. Its transactions kept their category.")
