from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.budgets.service import month_summary, sub_budget_states
from app.budgets.tracker import Tracker, group_total
from app.deps import DB, CurrentUser, render
from app.models import Transaction
from app.util import shift_month, this_month

router = APIRouter()


@router.get("/")
def home(request: Request, db: DB, user: CurrentUser, month: str | None = None):
    month = month or this_month()
    summary = month_summary(db, month)
    subs = sub_budget_states(db, "active")
    review_count = db.scalar(
        select(func.count()).where(
            Transaction.kind == "expense",
            Transaction.is_excluded.is_(False),
            Transaction.category_id.is_(None),
        )
    )
    has_data = db.scalar(select(Transaction.id).limit(1)) is not None
    trackers = {
        r.category.id: Tracker(budget=r.state.budget, carry=r.state.carry, spent=r.state.spent)
        for r in summary.rows
    }
    total = group_total(list(trackers.values()))
    total.spent += summary.uncategorised  # uncategorised spend still counts as spent
    return render(
        request,
        "home/index.html",
        month=month,
        prev_month=shift_month(month, -1),
        next_month=shift_month(month, 1),
        s=summary,
        subs=subs,
        review_count=review_count or 0,
        has_data=has_data,
        trackers=trackers,
        total=total,
        is_current=month == this_month(),
    )
