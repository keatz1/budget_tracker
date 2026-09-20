import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Category, Rule, Transaction
from tests.test_import import make_account, upload

FIX = Path(__file__).parent / "fixtures" / "csv"


@pytest.fixture()
def loaded(logged_in, db):
    card = make_account(db, "Chase card", "chase_card")
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    apple = make_account(db, "Apple Card", "apple_card")
    upload(logged_in, apple.id, FIX / "apple_card.csv")
    return logged_in


def exists(db, model, pk) -> bool:
    return db.scalar(select(func.count()).select_from(model).where(model.id == pk)) == 1


def cat_id(db, name):
    return db.scalar(select(Category.id).where(Category.name == name))


def test_list_pages_render(loaded, db):
    r = loaded.get("/transactions?month=2026-09")
    assert r.status_code == 200 and "TESCO STORES" in r.text and "Sep 2026" in r.text
    assert "Categorise" in r.text  # uncategorised chips
    r = loaded.get("/transactions?month=2026-09&show=transfer")
    assert "Payment Thank You" in r.text
    r = loaded.get("/transactions?month=all&show=all&q=kroger")
    assert "Kroger" in r.text and "TESCO" not in r.text
    assert loaded.get("/transactions?month=2026-09&card_holder=Sally+Example").status_code == 200


def test_manual_add_edit_delete(logged_in, db):
    make_account(db, "Cash", "chase_card")
    r = logged_in.post(
        "/transactions/new",
        data={"account_id": 1, "date": "2026-09-05", "description": "Farmers market",
              "amount": "23.50", "kind": "expense", "category_id": cat_id(db, "Groceries")},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    t = db.scalar(select(Transaction))
    assert t.amount == -2350 and t.source == "manual" and t.category_locked
    r = logged_in.post(
        "/transactions/new",
        data={"account_id": 1, "date": "2026-09-06", "description": "Refund", "amount": "10",
              "kind": "income"},
        follow_redirects=False,
    )  # fmt: skip
    db.expire_all()
    inc = db.scalar(select(Transaction).where(Transaction.kind == "income"))
    assert inc.amount == 1000
    r = logged_in.post(
        f"/transactions/{t.id}",
        data={"date": "2026-09-05", "description": "Market", "amount": "25", "kind": "expense",
              "category_id": "", "notes": "veg"},
        follow_redirects=False,
    )  # fmt: skip
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert t.amount == -2500 and t.notes == "veg" and t.category_id is None
    tid = t.id
    assert "History" in logged_in.get(f"/transactions/{tid}").text
    logged_in.post(f"/transactions/{tid}/delete", follow_redirects=False)
    db.expire_all()
    assert not exists(db, Transaction, tid)


def test_chip_category_change_returns_row(loaded, db):
    t = db.scalar(select(Transaction).where(Transaction.description_raw == "TESCO STORES"))
    gid = cat_id(db, "Groceries")
    r = loaded.post(f"/transactions/{t.id}/category", data={"category_id": gid})
    assert r.status_code == 200 and "Groceries" in r.text and f'id="txn-{t.id}"' in r.text
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert t.category_id == gid and t.category_locked
    r = loaded.post(f"/transactions/{t.id}/category", data={"category_id": "exclude"})
    db.expire_all()
    assert db.get(Transaction, t.id).is_excluded


def test_bulk_category_and_undo(loaded, db):
    ids = [
        t.id
        for t in db.scalars(
            select(Transaction).where(Transaction.merchant_name == "Belbim As. Ulasim")
        )
    ]
    tid = cat_id(db, "Transport")
    r = loaded.post(
        "/transactions/bulk",
        data={"ids": ids, "action": "category", "value": str(tid), "month": "2026-09",
              "show": "spend"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303 and "month=2026-09" in r.headers["location"]
    db.expire_all()
    assert all(db.get(Transaction, i).category_id == tid for i in ids)
    flash = r.cookies.get("bt_flash") or ""
    batch = re.search(r"bulkUndo\(\\?'?([0-9a-f-]{36})", flash).group(1)
    r = loaded.post(f"/transactions/bulk/undo/{batch}", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert all(db.get(Transaction, i).category_id is None for i in ids)


def test_bulk_select_all_in_filter(loaded, db):
    r = loaded.post(
        "/transactions/bulk",
        data={"all": "1", "action": "exclude", "month": "2026-09", "show": "spend", "q": "BELBIM"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    n = db.scalar(
        select(func.count()).where(
            Transaction.merchant_name == "Belbim As. Ulasim", Transaction.is_excluded.is_(True)
        )
    )
    assert n == 6
    # nothing else touched
    other = db.scalar(select(Transaction).where(Transaction.merchant_name == "Kroger"))
    assert not other.is_excluded


def test_bulk_delete(loaded, db):
    ids = [
        t.id for t in db.scalars(select(Transaction).where(Transaction.merchant_name == "Kroger"))
    ]
    before = db.scalar(select(func.count(Transaction.id)))
    loaded.post("/transactions/bulk", data={"ids": ids, "action": "delete"}, follow_redirects=False)
    db.expire_all()
    assert db.scalar(select(func.count(Transaction.id))) == before - len(ids)


def test_review_queue_groups_and_assign_makes_rule(loaded, db):
    r = loaded.get("/review")
    assert r.status_code == 200 and "Belbim As. Ulasim" in r.text and "6 transactions" in r.text
    tid = cat_id(db, "Transport")
    r = loaded.post(
        "/review/assign",
        data={
            "key": "BELBIM AS. ULASIM",
            "action": "category",
            "value": str(tid),
            "make_rule": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    belbim = db.scalars(
        select(Transaction).where(Transaction.merchant_name == "Belbim As. Ulasim")
    ).all()
    assert all(t.category_id == tid and t.category_locked for t in belbim)
    rule = db.scalar(select(Rule).where(Rule.pattern == "BELBIM AS. ULASIM"))
    assert rule and rule.category_id == tid
    assert "Belbim" not in loaded.get("/review").text

    # exclude a group without a rule
    r = loaded.post(
        "/review/assign", data={"key": "AMAZON MARKETPLACE", "action": "exclude"},
        follow_redirects=False,
    )  # fmt: skip
    db.expire_all()
    am = db.scalar(select(Transaction).where(Transaction.merchant_name == "Amazon Marketplace"))
    assert am.is_excluded
    assert db.scalar(select(func.count(Rule.id)).where(Rule.set_excluded.is_(True))) >= 1


def test_rule_create_applies_to_existing_and_respects_locks(loaded, db):
    gid = cat_id(db, "Groceries")
    tesco = db.scalar(select(Transaction).where(Transaction.description_raw == "TESCO STORES"))
    # lock TESCO by hand into Shopping
    loaded.post(f"/transactions/{tesco.id}/category", data={"category_id": cat_id(db, "Shopping")})
    r = loaded.post(
        "/rules/new",
        data={"name": "Groceries", "match_type": "regex", "pattern": "TESCO|KROGER|PUBLIX",
              "category_id": str(gid), "priority": "50", "is_enabled": "on",
              "apply_existing": "on"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    db.expire_all()
    kroger = db.scalar(select(Transaction).where(Transaction.merchant_name == "Kroger"))
    publix = db.scalar(select(Transaction).where(Transaction.description_raw == "PUBLIX #2039"))
    assert kroger.category_id == gid and publix.category_id == gid
    assert db.get(Transaction, tesco.id).category_id == cat_id(db, "Shopping")  # lock held
    assert "Groceries" in loaded.get("/rules").text
    r = loaded.get("/rules/test?match_type=contains&pattern=publix")
    assert "Matches 1 existing" in r.text
    # rule form prefill from a transaction
    r = loaded.get(f"/rules/new?from={kroger.id}")
    assert 'value="KROGER"' in r.text
    # a rule with no matcher is rejected
    r = loaded.post("/rules/new", data={"name": "empty", "priority": "1"})
    assert "needs a pattern" in r.text


def test_categories_crud_and_delete_moves_txns(loaded, db):
    r = loaded.post(
        "/categories/new",
        data={"name": "Dog", "group_name": "Home", "default_budget": "150", "colour": "#123456",
              "rollover_mode": "carry_positive_only", "rollover_cap": "300"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    dog = db.scalar(select(Category).where(Category.name == "Dog"))
    assert dog.default_budget == 15000 and dog.rollover_cap == 30000
    t = db.scalar(select(Transaction).where(Transaction.merchant_name == "Kroger"))
    loaded.post(f"/transactions/{t.id}/category", data={"category_id": dog.id})
    gid = cat_id(db, "Groceries")
    dog_id, t_id = dog.id, t.id
    loaded.post(f"/categories/{dog_id}/delete", data={"move_to": str(gid)}, follow_redirects=False)
    db.expire_all()
    assert not exists(db, Category, dog_id)
    assert db.get(Transaction, t_id).category_id == gid
    assert loaded.get("/categories").status_code == 200
