"""Import, dedupe, and rules-at-import tests on the synthetic fixtures."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import Account, CsvProfile, Import, Transaction

FIX = Path(__file__).parent / "fixtures" / "csv"


def make_account(db, name, slug, kind="credit"):
    profile = db.scalar(select(CsvProfile).where(CsvProfile.slug == slug))
    a = Account(name=name, kind=kind, csv_profile_id=profile.id)
    db.add(a)
    db.commit()
    return a


def upload(client, account_id, path: Path, **flags):
    with path.open("rb") as f:
        r = client.post(
            "/import/preview", data={"account_id": account_id}, files={"file": (path.name, f)}
        )
    assert r.status_code == 200, r.text
    import re

    sha = re.search(r'name="sha" value="([0-9a-f]+)"', r.text).group(1)
    data = {"account_id": account_id, "sha": sha, "filename": path.name, **flags}
    r2 = client.post("/import/commit", data=data, follow_redirects=False)
    assert r2.status_code == 303, r2.text
    return r.text


def count(db, account_id):
    return db.scalar(select(func.count(Transaction.id)).where(Transaction.account_id == account_id))


@pytest.fixture()
def card(logged_in, db):
    return make_account(db, "Chase card", "chase_card")


def test_overlapping_exports_add_only_new_rows(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    assert count(db, card.id) == 9

    preview = upload(logged_in, card.id, FIX / "chase_card_b.csv")
    assert count(db, card.id) == 12  # 3 new rows, 8 overlapping ones skipped
    assert ">3</div>" in preview  # the "New" tile

    # Identical same-day rows (two Paint Room -30.10 on 09/17) both survived.
    n = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.account_id == card.id, Transaction.description_raw == "TST-The Paint Room"
        )
    )
    assert n == 3  # two on 09/17 plus one on 09/19


def test_same_file_twice_adds_nothing(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    assert count(db, card.id) == 9
    imps = db.scalars(select(Import).order_by(Import.id)).all()
    assert [i.rows_new for i in imps] == [9, 0]
    assert imps[1].rows_duplicate == 9


def test_subset_export_adds_nothing(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_b.csv")
    before = count(db, card.id)
    upload(logged_in, card.id, FIX / "chase_card_a.csv")  # strict subset except PUBLIX row
    assert count(db, card.id) == before + 1  # PUBLIX 09/10 is only in A


def test_pending_to_posted_is_flagged_and_skipped_by_default(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    preview = upload(logged_in, card.id, FIX / "chase_card_pending.csv")
    assert "Needs a look" in preview
    assert count(db, card.id) == 9  # both flagged rows skipped by default


def test_flagged_row_can_be_kept(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    # row index 0 is WRAPS & WINGS (flagged against Wraps and Wings); keep it
    upload(logged_in, card.id, FIX / "chase_card_pending.csv", flag_0="keep")
    assert count(db, card.id) == 10


def test_card_payment_and_refund_kinds(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    pay = db.scalar(select(Transaction).where(Transaction.bank_type == "Payment"))
    assert pay.kind == "transfer" and pay.is_excluded and pay.amount == 290236
    ret = db.scalar(select(Transaction).where(Transaction.bank_type == "Return"))
    assert ret.kind == "expense" and ret.amount == 2499 and not ret.is_excluded


def test_chase_checking_trailing_comma_balance_and_rules(logged_in, db):
    acct = make_account(db, "Chase checking", "chase_checking", kind="checking")
    upload(logged_in, acct.id, FIX / "chase_checking.csv")
    assert count(db, acct.id) == 8
    rows = {t.description_raw[:12]: t for t in db.scalars(select(Transaction)).all()}
    assert rows["APPLECARD GS"].kind == "transfer" and rows["APPLECARD GS"].is_excluded
    assert rows["ACME CORP   "].kind == "income" and rows["ACME CORP   "].is_excluded
    assert rows["Online Realt"].kind == "transfer"  # ACCT_XFER
    assert rows["Payment to C"].kind == "transfer"  # LOAN_PMT + description
    assert rows["VENMO       "].kind == "expense" and not rows["VENMO       "].is_excluded
    assert rows["Zelle paymen"].kind == "income"  # QUICKPAY_CREDIT positive
    # Fingerprints differ even for same-day same-amount rows because balance differs.
    fps = {t.fingerprint for t in rows.values()}
    assert len(fps) == 8


def test_apple_card_sign_flip_duplicates_and_holder(logged_in, db):
    acct = make_account(db, "Apple Card", "apple_card")
    upload(logged_in, acct.id, FIX / "apple_card.csv")
    assert count(db, acct.id) == 10
    amazon = db.scalar(select(Transaction).where(Transaction.merchant_name == "Amazon Marketplace"))
    assert amazon.amount == -13707 and amazon.card_holder == "Sally Example"
    assert amazon.kind == "expense" and amazon.date.isoformat() == "2026-09-19"
    pay = db.scalar(select(Transaction).where(Transaction.bank_type == "Payment"))
    assert pay.amount == 524041 and pay.kind == "transfer" and pay.is_excluded
    belbim = db.scalars(
        select(Transaction).where(Transaction.merchant_name == "Belbim As. Ulasim")
    ).all()
    assert len(belbim) == 6 and len({t.fingerprint for t in belbim}) == 6
    # re-import: nothing new, all six identical rows recognised
    upload(logged_in, acct.id, FIX / "apple_card.csv")
    assert count(db, acct.id) == 10


def test_undo_import_keeps_edited_rows(logged_in, db, card):
    upload(logged_in, card.id, FIX / "chase_card_a.csv")
    imp = db.scalar(select(Import))
    t = db.scalar(select(Transaction).where(Transaction.description_raw == "TESCO STORES"))
    t.notes = "weekly shop"
    db.commit()
    r = logged_in.post(f"/import/{imp.id}/undo", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert count(db, card.id) == 1
    kept = db.scalar(select(Transaction))
    assert kept.notes == "weekly shop" and kept.import_id is None


def test_wrong_profile_gives_readable_error(logged_in, db):
    acct = make_account(db, "Apple Card", "chase_card")  # wrong on purpose
    with (FIX / "apple_card.csv").open("rb") as f:
        r = logged_in.post(
            "/import/preview", data={"account_id": acct.id}, files={"file": ("x.csv", f)}
        )
    assert "not found" in r.text and "Purchased By" in r.text


def test_custom_profile_flow(logged_in, db):
    c = logged_in
    r = c.post("/import/profiles/sample", data={"headers": "Date,Details,Money Out,Money In,Bal"})
    assert "<select" in r.text and "Money Out" in r.text
    r = c.post(
        "/import/profiles/new",
        data={
            "name": "My bank",
            "col_date": "Date",
            "col_description": "Details",
            "col_debit": "Money Out",
            "col_credit": "Money In",
            "col_balance": "Bal",
            "date_format": "%Y-%m-%d",
            "positive_kind": "income",
            "skip_rows": "0",
        },  # fmt: skip
        follow_redirects=False,
    )
    assert r.status_code == 303
    p = db.scalar(select(CsvProfile).where(CsvProfile.name == "My bank"))
    assert p.col_debit == "Money Out" and p.col_amount is None
    from app.importer.parser import parse_csv

    rows = parse_csv(
        b"Date,Details,Money Out,Money In,Bal\n2026-09-01,SHOP,12.50,,100.00\n"
        b"2026-09-02,SALARY,,1000.00,1100.00\n",
        p,
    )
    assert [r.amount for r in rows] == [-1250, 100000]
    assert [r.kind for r in rows] == ["expense", "income"]
