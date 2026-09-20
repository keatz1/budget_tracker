from pathlib import Path

from sqlalchemy import select

from app.models import Category, Transaction
from tests.test_import import make_account, upload

FIX = Path(__file__).parent / "fixtures" / "csv"


def test_dashboards_render_with_and_without_data(logged_in, db):
    r = logged_in.get("/dashboards")
    assert r.status_code == 200 and "Budget vs spending" in r.text
    card = make_account(db, "Apple Card", "apple_card")
    upload(logged_in, card.id, FIX / "apple_card.csv")
    g = db.scalar(select(Category).where(Category.name == "Groceries"))
    g.default_budget = 50000
    db.commit()
    kroger = db.scalar(select(Transaction).where(Transaction.merchant_name == "Kroger"))
    logged_in.post(f"/transactions/{kroger.id}/category", data={"category_id": g.id})
    r = logged_in.get("/dashboards?month=2026-09")
    assert r.status_code == 200
    assert '"Groceries"' in r.text and "Kroger" in r.text and "Sally" in r.text
    assert "Spending by person" in r.text  # two card holders in the fixture
    r = logged_in.get(f"/dashboards?month=2026-09&category_id={g.id}")
    assert '"name": "Groceries"' in r.text
