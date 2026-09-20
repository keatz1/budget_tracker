"""Budget, rollover and sub-budget maths. All amounts are positive cents
(spend is reported as a positive number here, even though transactions store it negative)."""

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Budget, Category, SubBudget, Transaction
from app.util import month_bounds, month_key, months_between, shift_month

MAX_LOOKBACK_MONTHS = 60


@dataclass
class MonthState:
    month: str
    budget: int  # this month's budget (override or default)
    carry: int  # carried in from last month (can be negative in carry_all)
    spent: int
    sub_budget_spent: int = 0  # portion of `spent` that belongs to sub-budgets

    @property
    def received(self) -> int:
        """For income categories: money in, as a positive number."""
        return -self.spent

    @property
    def available(self) -> int:
        return self.budget + self.carry

    @property
    def remaining(self) -> int:
        return self.available - self.spent

    @property
    def pct(self) -> float:
        if self.available <= 0:
            return 100.0 if self.spent > 0 else 0.0
        return min(100.0, self.spent / self.available * 100)

    @property
    def over(self) -> bool:
        return self.spent > self.available


def clamp_carry(category: Category, diff: int) -> int:
    mode = category.rollover_mode
    if mode == "none":
        return 0
    if mode == "carry_positive_only":
        diff = max(diff, 0)
    if category.rollover_cap is not None and diff > category.rollover_cap:
        diff = category.rollover_cap
    return diff


def budgets_for(db: Session, months: list[str]) -> dict[tuple[int, str], int]:
    rows = db.execute(
        select(Budget.category_id, Budget.month, Budget.amount).where(Budget.month.in_(months))
    )
    return {(cid, m): amt for cid, m, amt in rows}


def spend_by_category(
    db: Session, start: str, end: str
) -> dict[tuple[int | None, str], tuple[int, int]]:
    """(category_id, month) -> (spent, spent_in_sub_budgets), positive cents.

    Income rows assigned to a category count as negative spend, so a reimbursement put
    under Groceries reduces Groceries, and an income category comes out negative
    (money received). Uncategorised income is left out; only uncategorised expenses
    land in the (None, month) bucket."""
    lo, _ = month_bounds(start)
    _, hi = month_bounds(end)
    ym = func.strftime("%Y-%m", Transaction.date)
    rows = db.execute(
        select(
            Transaction.category_id,
            ym,
            func.sum(-Transaction.amount),
            func.sum(func.iif(Transaction.sub_budget_id.isnot(None), -Transaction.amount, 0)),
        )
        .where(
            Transaction.kind != "transfer",
            Transaction.is_excluded.is_(False),
            or_(Transaction.category_id.isnot(None), Transaction.kind == "expense"),
            Transaction.date >= lo,
            Transaction.date <= hi,
        )
        .group_by(Transaction.category_id, ym)
    )
    return {(cid, m): (int(s or 0), int(sb or 0)) for cid, m, s, sb in rows}


def anchor_month(db: Session, category: Category, up_to: str) -> str:
    if category.rollover_start:
        return min(category.rollover_start, up_to)
    first = db.scalar(
        select(func.min(Transaction.date)).where(
            Transaction.category_id == category.id, Transaction.kind != "transfer"
        )
    )
    if first is None:
        return up_to
    start = month_key(first)
    floor = shift_month(up_to, -MAX_LOOKBACK_MONTHS)
    return max(start, floor)


def rollover_series(
    db: Session,
    category: Category,
    up_to: str,
    budgets: dict[tuple[int, str], int] | None = None,
    spend: dict[tuple[int | None, str], tuple[int, int]] | None = None,
) -> list[MonthState]:
    """Month by month from the category's anchor to `up_to`, carrying balances forward."""
    start = anchor_month(db, category, up_to)
    months = months_between(start, up_to)
    if budgets is None:
        budgets = budgets_for(db, months)
    if spend is None:
        spend = spend_by_category(db, start, up_to)
    out: list[MonthState] = []
    carry = 0
    for m in months:
        budget = budgets.get((category.id, m), category.default_budget)
        spent, sub = spend.get((category.id, m), (0, 0))
        state = MonthState(month=m, budget=budget, carry=carry, spent=spent, sub_budget_spent=sub)
        out.append(state)
        carry = clamp_carry(category, state.available - state.spent)
    return out


@dataclass
class CategoryMonth:
    category: Category
    state: MonthState


@dataclass
class MonthSummary:
    month: str
    rows: list[CategoryMonth] = field(default_factory=list)
    uncategorised: int = 0  # spend with no category
    income_categories: list[CategoryMonth] = field(default_factory=list)

    @property
    def total_income(self) -> int:
        return sum(r.state.received for r in self.income_categories)

    @property
    def total_budget(self) -> int:
        return sum(r.state.budget for r in self.rows)

    @property
    def total_available(self) -> int:
        return sum(r.state.available for r in self.rows)

    @property
    def total_spent(self) -> int:
        return sum(r.state.spent for r in self.rows) + self.uncategorised

    @property
    def total_remaining(self) -> int:
        return self.total_available - self.total_spent

    @property
    def pct(self) -> float:
        if self.total_available <= 0:
            return 100.0 if self.total_spent else 0.0
        return min(100.0, self.total_spent / self.total_available * 100)


def month_summary(db: Session, month: str) -> MonthSummary:
    cats = db.scalars(
        select(Category)
        .where(Category.is_archived.is_(False))
        .order_by(Category.group_name, Category.sort_order, Category.name)
    ).all()
    lookback = shift_month(month, -MAX_LOOKBACK_MONTHS)
    spend = spend_by_category(db, lookback, month)
    budgets = budgets_for(db, months_between(lookback, month))
    summary = MonthSummary(month=month)
    for c in cats:
        series = rollover_series(db, c, month, budgets, spend)
        cm = CategoryMonth(category=c, state=series[-1])
        (summary.income_categories if c.kind == "income" else summary.rows).append(cm)
    summary.uncategorised = spend.get((None, month), (0, 0))[0]
    return summary


# --- sub-budgets -----------------------------------------------------------


@dataclass
class SubBudgetState:
    sub: SubBudget
    spent: int
    count: int

    @property
    def remaining(self) -> int:
        return self.sub.total_amount - self.spent

    @property
    def pct(self) -> float:
        if self.sub.total_amount <= 0:
            return 100.0 if self.spent else 0.0
        return min(100.0, self.spent / self.sub.total_amount * 100)

    @property
    def over(self) -> bool:
        return self.spent > self.sub.total_amount

    @property
    def days_left(self) -> int | None:
        if not self.sub.end_date:
            return None
        return (self.sub.end_date - dt.date.today()).days


def sub_budget_states(db: Session, status: str | None = "active") -> list[SubBudgetState]:
    stmt = select(SubBudget).order_by(SubBudget.start_date.desc())
    if status:
        stmt = stmt.where(SubBudget.status == status)
    subs = db.scalars(stmt).all()
    totals = {
        sid: (int(s or 0), int(n or 0))
        for sid, s, n in db.execute(
            select(Transaction.sub_budget_id, func.sum(-Transaction.amount), func.count())
            .where(
                Transaction.kind == "expense",
                Transaction.is_excluded.is_(False),
                Transaction.sub_budget_id.isnot(None),
            )
            .group_by(Transaction.sub_budget_id)
        )
    }
    out = []
    for s in subs:
        spent, n = totals.get(s.id, (0, 0))
        out.append(SubBudgetState(sub=s, spent=spent, count=n))
    return sorted(out, key=lambda st: -st.pct)


def sub_budget_cumulative(db: Session, sub: SubBudget) -> list[tuple[str, int]]:
    """(date, cumulative spent) points for the sub-budget's chart."""
    rows = db.execute(
        select(Transaction.date, func.sum(-Transaction.amount))
        .where(
            Transaction.sub_budget_id == sub.id,
            Transaction.kind == "expense",
            Transaction.is_excluded.is_(False),
        )
        .group_by(Transaction.date)
        .order_by(Transaction.date)
    ).all()
    out: list[tuple[str, int]] = [(sub.start_date.isoformat(), 0)]
    total = 0
    for d, amt in rows:
        total += int(amt or 0)
        out.append((d.isoformat(), total))
    return out
