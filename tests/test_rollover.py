"""Table-driven rollover and summary tests. Amounts in cents."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.budgets.service import (
    clamp_carry,
    month_summary,
    rollover_series,
    sub_budget_states,
)
from app.models import Account, Budget, Category, SubBudget, Transaction


def spend(db, cat, day: str, cents: int, **kw):
    acct = db.scalar(select(Account)) or Account(name="A", kind="credit")
    db.add(acct)
    db.flush()
    t = Transaction(
        account_id=acct.id,
        date=dt.date.fromisoformat(day),
        description_raw="x",
        description_clean="X",
        amount=-cents,
        kind="expense",
        category_id=cat.id if cat else None,
        source="manual",
        **kw,
    )
    db.add(t)
    db.commit()
    return t


@pytest.mark.parametrize(
    "mode,cap,diff,expected",
    [
        ("carry_all", None, 5000, 5000),
        ("carry_all", None, -3000, -3000),
        ("carry_positive_only", None, -3000, 0),
        ("carry_positive_only", None, 2000, 2000),
        ("none", None, 9999, 0),
        ("carry_all", 4000, 9000, 4000),
        ("carry_all", 4000, -9000, -9000),  # cap only limits the upside
    ],
)
def test_clamp_carry(mode, cap, diff, expected):
    c = Category(name="c", rollover_mode=mode, rollover_cap=cap)
    assert clamp_carry(c, diff) == expected


def test_series_carry_all(logged_in, db):
    c = Category(name="Groceries", default_budget=50000, rollover_mode="carry_all")
    db.add(c)
    db.commit()
    spend(db, c, "2026-06-10", 40000)  # under by 100
    spend(db, c, "2026-07-10", 70000)  # over by 100 + 100 carry -> -100
    spend(db, c, "2026-08-10", 10000)
    series = rollover_series(db, c, "2026-09")
    assert [s.month for s in series] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert [s.carry for s in series] == [0, 10000, -10000, 30000]
    assert [s.available for s in series] == [50000, 60000, 40000, 80000]
    assert series[1].over and series[1].remaining == -10000
    assert series[3].spent == 0 and series[3].remaining == 80000


def test_series_positive_only_and_cap(logged_in, db):
    c = Category(
        name="Fun", default_budget=10000, rollover_mode="carry_positive_only", rollover_cap=15000
    )
    db.add(c)
    db.commit()
    spend(db, c, "2026-05-01", 20000)  # over: forgiven
    spend(db, c, "2026-06-01", 0)  # nothing spent: carry 100
    # July: nothing spent, carry would be 200, capped at 150
    series = rollover_series(db, c, "2026-08")
    assert [s.carry for s in series] == [0, 0, 10000, 15000]


def test_month_override_beats_default(logged_in, db):
    c = Category(name="Travel", default_budget=20000, rollover_mode="none")
    db.add(c)
    db.commit()
    db.add(Budget(category_id=c.id, month="2026-09", amount=150000))
    spend(db, c, "2026-08-01", 5000)
    db.commit()
    series = rollover_series(db, c, "2026-09")
    assert series[-1].budget == 150000 and series[-2].budget == 20000
    assert all(s.carry == 0 for s in series)


def test_rollover_start_anchor(logged_in, db):
    c = Category(name="Pets", default_budget=10000, rollover_start="2026-08")
    db.add(c)
    db.commit()
    spend(db, c, "2026-01-01", 100000)  # ancient overspend must not count
    series = rollover_series(db, c, "2026-09")
    assert [s.month for s in series] == ["2026-08", "2026-09"]
    assert series[-1].carry == 10000


def test_refund_reduces_spend(logged_in, db):
    c = Category(name="Shopping", default_budget=10000, rollover_mode="none")
    db.add(c)
    db.commit()
    spend(db, c, "2026-09-01", 8000)
    spend(db, c, "2026-09-02", -3000)  # a refund: positive amount
    series = rollover_series(db, c, "2026-09")
    assert series[-1].spent == 5000


def test_month_summary_totals_include_uncategorised_and_sub_budgets(logged_in, db):
    for c in db.scalars(select(Category)).all():  # drop seeded categories for a clean total
        db.delete(c)
    g = Category(name="Groceries", default_budget=50000, rollover_mode="none")
    t = Category(name="Travel", default_budget=30000, rollover_mode="none")
    db.add_all([g, t])
    db.commit()
    trip = SubBudget(
        category_id=t.id, name="Trip", total_amount=100000, start_date=dt.date(2026, 9, 1)
    )
    db.add(trip)
    db.commit()
    spend(db, g, "2026-09-03", 12000)
    spend(db, t, "2026-09-04", 25000, sub_budget_id=trip.id)  # counts in Travel AND the trip
    spend(db, None, "2026-09-05", 4000)  # uncategorised
    spend(db, g, "2026-09-06", 999, is_excluded=True)  # excluded: ignored
    s = month_summary(db, "2026-09")
    assert s.total_budget == 80000 and s.total_available == 80000
    assert s.total_spent == 12000 + 25000 + 4000
    assert s.uncategorised == 4000
    travel = next(r for r in s.rows if r.category.name == "Travel")
    assert travel.state.spent == 25000 and travel.state.sub_budget_spent == 25000
    st = sub_budget_states(db)[0]
    assert st.spent == 25000 and st.remaining == 75000 and st.count == 1 and st.pct == 25.0


def test_month_before_any_transaction_is_empty_not_an_error(logged_in, db):
    c = Category(name="Pets", default_budget=10000)
    db.add(c)
    db.commit()
    spend(db, c, "2026-08-01", 500)
    series = rollover_series(db, c, "2020-01")
    assert [s.month for s in series] == ["2020-01"] and series[0].spent == 0
    assert logged_in.get("/?month=2020-01").status_code == 200
