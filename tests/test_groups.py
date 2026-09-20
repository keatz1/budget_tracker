import datetime as dt

from sqlalchemy import select

from app.models import Category
from app.budgets.tracker import Tracker
from tests.test_rollover import spend


def test_tracker_maths():
    # overspent last month by 100, budget 500, spent 250 -> 350 used of 500
    t = Tracker(budget=50000, carry=-10000, spent=25000)
    assert t.deficit == 10000 and t.surplus == 0 and t.track == 50000
    assert t.used == 35000 and t.left == 15000 and not t.over and t.budget_mark is None
    # surplus of 100 carried in: track grows to 600, budget mark at 500/600
    t = Tracker(budget=50000, carry=10000, spent=25000)
    assert t.track == 60000 and t.used == 25000 and t.left == 35000
    assert round(t.budget_mark, 1) == 83.3
    # over: used exceeds track, bar clamps at 100
    t = Tracker(budget=10000, carry=-5000, spent=8000)
    assert t.over and t.left == -3000 and t.pct(t.spent) < 100 and t.pct(t.used) == 100.0


def test_groups_page(logged_in, db):
    for c in db.scalars(select(Category)).all():
        db.delete(c)
    g = Category(name="Groceries", group_name="Everyday", default_budget=50000)
    r = Category(name="Restaurants", group_name="Everyday", default_budget=30000)
    p = Category(name="Pets", group_name="Home", default_budget=10000)
    db.add_all([g, r, p])
    db.commit()
    spend(db, g, "2026-08-10", 60000)  # over by 100 -> deficit carried into Sep
    spend(db, r, "2026-08-10", 20000)  # under by 100 -> surplus carried into Sep
    spend(db, g, "2026-09-05", 20000)
    spend(db, r, "2026-09-06", 5000)
    spend(db, p, "2026-09-07", 2500)
    page = logged_in.get("/groups?month=2026-09").text
    assert "Everyday" in page and "Home" in page and "All groups" in page
    # Everyday totals: budget 800, carry 0 (−100 + 100), spent 250
    assert "$800.00" in page and "$250.00" in page
    # Groceries row: 100 deficit + 200 spent = 300 used of 500
    assert "$300.00</strong> of $500.00" in page and "overspend carried in" in page
    # Restaurants row: 50 used of 400 (300 + 100 surplus), with a budget mark
    assert "$50.00</strong> of $400.00" in page and 'class="mark"' in page
    one = logged_in.get("/groups?month=2026-09&group=Home").text
    assert "Pets" in one and "Groceries" not in one and "All groups" not in one
    early = logged_in.get("/groups?month=2020-01").text  # budgets apply, nothing spent
    assert "$0.00</strong> of $500.00" in early
    assert dt.date.today()  # keep the import used


def test_group_total_keeps_gross_carries():
    from app.budgets.tracker import group_total

    t = group_total([Tracker(50000, -12000, 0), Tracker(30000, 12000, 0)])
    assert t.carry == 0 and t.gross_surplus == 12000 and t.gross_deficit == 12000
    assert t.track == 80000 and t.used == 0  # net zero carry: plain budget, nothing used
