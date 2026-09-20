"""Aggregates that feed the dashboards. Every chart reads from here."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.budgets.service import (
    MAX_LOOKBACK_MONTHS,
    MonthState,
    budgets_for,
    rollover_series,
    spend_by_category,
)
from app.models import Category, Transaction
from app.util import month_bounds, months_between, shift_month

OTHER_COLOUR = "#9ca3af"


def all_series(
    db: Session, end: str
) -> tuple[Sequence[Category], dict[int, dict[str, MonthState]]]:
    cats = db.scalars(
        select(Category)
        .where(Category.is_archived.is_(False), Category.kind == "expense")
        .order_by(Category.group_name, Category.sort_order, Category.name)
    ).all()
    lookback = shift_month(end, -MAX_LOOKBACK_MONTHS)
    spend = spend_by_category(db, lookback, end)
    budgets = budgets_for(db, months_between(lookback, end))
    out: dict[int, dict[str, MonthState]] = {}
    for c in cats:
        out[c.id] = {s.month: s for s in rollover_series(db, c, end, budgets, spend)}
    return cats, out


@dataclass
class MonthTotals:
    month: str
    budget: int  # sum of available (budget + carry)
    spent: int  # categorised + uncategorised spend


def monthly_totals(
    db: Session, months: list[str], series, uncat: dict[str, int]
) -> list[MonthTotals]:
    out = []
    for m in months:
        budget = sum(st[m].available for st in series.values() if m in st)
        spent = sum(st[m].spent for st in series.values() if m in st) + uncat.get(m, 0)
        out.append(MonthTotals(m, budget, spent))
    return out


def uncategorised_by_month(db: Session, start: str, end: str) -> dict[str, int]:
    return {
        m: int(s or 0)
        for (cid, m), (s, _) in spend_by_category(db, start, end).items()
        if cid is None
    }


def top_categories(cats, series, months: list[str], limit: int = 7):
    """Categories ranked by spend over the window; the rest fold into Other."""
    totals = {c.id: sum(series[c.id][m].spent for m in months if m in series[c.id]) for c in cats}
    ranked = sorted(cats, key=lambda c: -totals[c.id])
    top = [c for c in ranked[:limit] if totals[c.id] > 0]
    rest = [c for c in ranked if c not in top]
    return top, rest


def top_merchants(db: Session, start: str, end: str, limit: int = 10) -> list[tuple[str, int, int]]:
    lo, _ = month_bounds(start)
    _, hi = month_bounds(end)
    name = func.coalesce(Transaction.merchant_name, Transaction.description_clean)
    rows = db.execute(
        select(name, func.sum(-Transaction.amount), func.count())
        .where(
            Transaction.kind == "expense",
            Transaction.is_excluded.is_(False),
            Transaction.date >= lo,
            Transaction.date <= hi,
        )
        .group_by(name)
        .order_by(func.sum(-Transaction.amount).desc())
        .limit(limit)
    )
    return [(n, int(s), int(c)) for n, s, c in rows]


def spend_by_holder(db: Session, start: str, end: str) -> dict[str, dict[str, int]]:
    """holder -> month -> spent. Only rows where the card reports a holder."""
    lo, _ = month_bounds(start)
    _, hi = month_bounds(end)
    ym = func.strftime("%Y-%m", Transaction.date)
    rows = db.execute(
        select(Transaction.card_holder, ym, func.sum(-Transaction.amount))
        .where(
            Transaction.kind == "expense",
            Transaction.is_excluded.is_(False),
            Transaction.card_holder.isnot(None),
            Transaction.date >= lo,
            Transaction.date <= hi,
        )
        .group_by(Transaction.card_holder, ym)
    )
    out: dict[str, dict[str, int]] = {}
    for holder, m, s in rows:
        out.setdefault(holder, {})[m] = int(s or 0)
    return out
