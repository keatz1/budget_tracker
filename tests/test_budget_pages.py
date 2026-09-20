import datetime as dt
from pathlib import Path

from sqlalchemy import select

from app.models import Budget, Category, SubBudget, Transaction
from tests.test_import import make_account, upload

FIX = Path(__file__).parent / "fixtures" / "csv"


def test_home_and_budgets_pages(logged_in, db):
    r = logged_in.get("/")
    assert r.status_code == 200 and "get set up" in r.text
    card = make_account(db, "Chase card", "chase_card")
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    g = db.scalar(select(Category).where(Category.name == "Groceries"))
    tesco = db.scalar(select(Transaction).where(Transaction.description_raw == "TESCO STORES"))
    logged_in.post(f"/transactions/{tesco.id}/category", data={"category_id": g.id})
    r = logged_in.post(
        "/budgets?month=2026-09",
        data={f"default_{g.id}": "500", f"month_{g.id}": "650"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Category, g.id).default_budget == 50000
    assert db.scalar(select(Budget.amount).where(Budget.category_id == g.id)) == 65000
    r = logged_in.get("/?month=2026-09")
    assert "$650.00" in r.text and "$19.60" in r.text and "Uncategorised" in r.text
    r = logged_in.get("/budgets?month=2026-09")
    assert 'value="650.00"' in r.text
    # copy last month's overrides forward
    r = logged_in.post("/budgets/copy-last?month=2026-10", follow_redirects=False)
    assert r.status_code == 303
    assert db.scalar(select(Budget.amount).where(Budget.month == "2026-10")) == 65000
    # clearing the override deletes the row
    logged_in.post("/budgets?month=2026-10", data={f"month_{g.id}": ""}, follow_redirects=False)
    db.expire_all()
    assert db.scalar(select(Budget.id).where(Budget.month == "2026-10")) is None


def test_sub_budget_flow(logged_in, db):
    card = make_account(db, "Apple Card", "apple_card")
    upload(logged_in, card.id, FIX / "apple_card.csv")
    travel = db.scalar(select(Category).where(Category.name == "Travel"))
    r = logged_in.post(
        "/sub-budgets/new",
        data={"name": "Istanbul trip", "category_id": travel.id, "total_amount": "4000",
              "start_date": "2026-09-01", "end_date": "2026-09-14"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    sb = db.scalar(select(SubBudget))
    assert sb.total_amount == 400000 and sb.end_date == dt.date(2026, 9, 14)
    # assign via bulk edit
    ids = [
        t.id
        for t in db.scalars(
            select(Transaction).where(Transaction.merchant_name == "Belbim As. Ulasim")
        )
    ]
    logged_in.post(
        "/transactions/bulk", data={"ids": ids, "action": "category", "value": str(travel.id)},
        follow_redirects=False,
    )  # fmt: skip
    logged_in.post(
        "/transactions/bulk", data={"ids": ids, "action": "sub_budget", "value": str(sb.id)},
        follow_redirects=False,
    )  # fmt: skip
    r = logged_in.get(f"/sub-budgets/{sb.id}")
    assert r.status_code == 200 and "$6.96" in r.text and "6</div>" in r.text
    assert "Istanbul trip" in logged_in.get("/").text
    assert "Istanbul trip" in logged_in.get("/sub-budgets").text
    r = logged_in.post(f"/sub-budgets/{sb.id}/toggle", follow_redirects=False)
    db.expire_all()
    assert db.get(SubBudget, sb.id).status == "closed"
    r = logged_in.post(
        f"/sub-budgets/{sb.id}/edit",
        data={"name": "Trip", "category_id": travel.id, "total_amount": "5000",
              "start_date": "2026-09-01"},
        follow_redirects=False,
    )  # fmt: skip
    db.expire_all()
    assert db.get(SubBudget, sb.id).total_amount == 500000
    logged_in.post(f"/sub-budgets/{sb.id}/delete", follow_redirects=False)
    db.expire_all()
    t = db.get(Transaction, ids[0])
    assert t.sub_budget_id is None and t.category_id == travel.id
