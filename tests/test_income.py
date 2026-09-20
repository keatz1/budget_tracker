from pathlib import Path

from sqlalchemy import select

from app.models import Category, Transaction
from tests.test_import import make_account, upload

FIX = Path(__file__).parent / "fixtures" / "csv"


def add(client, **data):
    base = {"account_id": 1, "date": "2026-09-05", "kind": "income", "description": "x"}
    r = client.post("/transactions/new", data={**base, **data}, follow_redirects=False)
    assert r.status_code == 303


def test_income_categories_are_seeded(logged_in, db):
    names = set(db.scalars(select(Category.name).where(Category.kind == "income")))
    assert {"Salary", "Reimbursements", "Other income"} <= names


def test_income_into_income_category_shows_on_home(logged_in, db):
    make_account(db, "Chase checking", "chase_checking", kind="checking")
    salary = db.scalar(select(Category).where(Category.name == "Salary"))
    add(logged_in, description="Payday", amount="1542.05", category_id=salary.id)
    t = db.scalar(select(Transaction))
    assert t.kind == "income" and t.category_id == salary.id and t.amount == 154205
    home = logged_in.get("/?month=2026-09").text
    assert "Income" in home and "+$1,542.05" in home and "Salary" in home
    # the row shows the category chip and the income marker
    rows = logged_in.get("/transactions?month=2026-09&show=income").text
    assert "Salary" in rows and ">income<" in rows
    # income never counts as spending
    assert (
        "$1,542.05" not in logged_in.get("/dashboards?month=2026-09").text.split("Share")[1][:2000]
    )


def test_income_into_expense_category_offsets_spend(logged_in, db):
    make_account(db, "Cash", "chase_card")
    g = db.scalar(select(Category).where(Category.name == "Groceries"))
    g.default_budget = 50000
    db.commit()
    logged_in.post(
        "/transactions/new",
        data={"account_id": 1, "date": "2026-09-03", "kind": "expense", "description": "Publix",
              "amount": "80", "category_id": g.id},
        follow_redirects=False,
    )  # fmt: skip
    add(logged_in, description="Sally paid me back", amount="30", category_id=g.id)
    home = logged_in.get("/?month=2026-09").text
    assert "$50.00</strong> of $500.00" in home  # 80 spent, 30 back


def test_uncategorised_income_appears_in_review_and_can_be_assigned(logged_in, db):
    acct = make_account(db, "Chase checking", "chase_checking", kind="checking")
    upload(logged_in, acct.id, FIX / "chase_checking.csv")
    r = logged_in.get("/review").text
    assert "Income without a category" in r and "Zelle Payment From Jane Doe" in r
    other = db.scalar(select(Category).where(Category.name == "Other income"))
    import re

    key = re.search(r'name="key" value="(ZELLE[^"]*)"', r).group(1)
    r = logged_in.post(
        "/review/assign",
        data={"key": key, "kind": "income", "action": "category", "value": str(other.id),
              "make_rule": "1"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    db.expire_all()
    z = db.scalar(select(Transaction).where(Transaction.description_raw.like("Zelle%")))
    assert z.category_id == other.id and z.kind == "income"
    assert "Zelle" not in logged_in.get("/review").text
    # tapping the chip on an income row works too
    r = logged_in.post(f"/transactions/{z.id}/category", data={"category_id": ""})
    assert r.status_code == 200 and "Categorise" in r.text
