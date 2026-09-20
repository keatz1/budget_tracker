"""Populate the configured database with a demo user, accounts, the fixture CSVs,
budgets and a sub-budget. Used by the screenshot job. Safe to re-run.

  BT_DATABASE_PATH=/tmp/demo.db uv run python scripts/demo_data.py
Login: demo@example.com / demo-password
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.auth.service import hash_password  # noqa: E402
from app.db import SessionLocal, run_migrations  # noqa: E402
from app.importer import service  # noqa: E402
from app.models import Account, Budget, Category, CsvProfile, SubBudget, User  # noqa: E402
from app.rules.engine import apply_rules  # noqa: E402
from app.seed import seed  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "csv"


def main() -> None:
    run_migrations()
    with SessionLocal() as db:
        seed(db)
        user = db.scalar(select(User).where(User.email == "demo@example.com"))
        if user is None:
            user = User(
                email="demo@example.com",
                display_name="Demo",
                password_hash=hash_password("demo-password"),
                is_admin=True,
            )
            db.add(user)
            db.commit()
        if db.scalar(select(Account.id).limit(1)):
            print("demo data already present")
            return

        def acct(name, slug, kind):
            p = db.scalar(select(CsvProfile).where(CsvProfile.slug == slug))
            a = Account(name=name, kind=kind, csv_profile_id=p.id)
            db.add(a)
            db.commit()
            db.refresh(a)
            return a

        for name, slug, kind, fn in [
            ("Chase card", "chase_card", "credit", "chase_card_b.csv"),
            ("Chase checking", "chase_checking", "checking", "chase_checking.csv"),
            ("Apple Card", "apple_card", "credit", "apple_card.csv"),
        ]:
            a = acct(name, slug, kind)
            st = service.stage(db, a, fn, (FIX / fn).read_bytes())
            service.commit(db, a, user, st, set())

        cats = {c.name: c for c in db.scalars(select(Category)).all()}
        for name, amt in [("Groceries", 600), ("Restaurants", 300), ("Transport", 120),
                          ("Shopping", 200), ("Subscriptions", 60), ("Travel", 400),
                          ("Pets", 100), ("Coffee", 40)]:  # fmt: skip
            cats[name].default_budget = amt * 100
        month = dt.date.today().strftime("%Y-%m")
        db.add(Budget(category_id=cats["Travel"].id, month=month, amount=150000))
        trip = SubBudget(
            category_id=cats["Travel"].id,
            name="Istanbul trip",
            total_amount=400000,
            start_date=dt.date(2026, 9, 1),
            end_date=dt.date(2026, 9, 14),
        )
        db.add(trip)
        db.commit()

        from app.models import Rule, Transaction

        rules = [
            Rule(name="Groceries", match_type="regex", pattern="TESCO|KROGER|PUBLIX|FACTOR75",
                 category_id=cats["Groceries"].id, priority=50),
            Rule(name="Restaurants", match_type="regex",
                 pattern="PAINT ROOM|WRAPS|CHICK-FIL-A|STARBUCKS",
                 category_id=cats["Restaurants"].id, priority=50),
            Rule(name="Istanbul transit", match_type="contains", pattern="BELBIM",
                 category_id=cats["Travel"].id, sub_budget_id=trip.id, priority=40),
            Rule(name="Amazon", match_type="contains", pattern="AMAZON",
                 category_id=cats["Shopping"].id, merchant_name="Amazon", priority=60),
        ]  # fmt: skip
        db.add_all(rules)
        db.flush()
        apply_rules(db, db.scalars(select(Transaction)).all())
        db.commit()
        print("demo data loaded")


if __name__ == "__main__":
    main()
