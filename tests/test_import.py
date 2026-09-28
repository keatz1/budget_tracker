"""Import, dedupe, and rules-at-import tests on the synthetic fixtures."""

import datetime as dt
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
    """Preview then commit one file. The account is detected from the file; the
    account_id argument is only used to confirm what was detected."""
    with path.open("rb") as f:
        r = client.post("/import/preview", files={"files": (path.name, f)})
    assert r.status_code == 200, r.text
    import re

    sha = re.search(r'name="sha_0" value="([0-9a-f]+)"', r.text).group(1)
    detected = re.search(r'name="account_id_0".*?value="(\d+)" selected', r.text, re.S).group(1)
    assert int(detected) == account_id, "detected the wrong account"
    data = {"account_id_0": account_id, "sha_0": sha, "filename_0": path.name}
    data.update({k.replace("flag_", "flag_0_"): v for k, v in flags.items()})
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


def test_unknown_layout_and_missing_account_give_readable_errors(logged_in, db):
    make_account(db, "Chase card", "chase_card")
    with (FIX / "apple_card.csv").open("rb") as f:
        r = logged_in.post("/import/preview", files={"files": ("x.csv", f)})
    assert "looks like a Apple Card export, but no account uses that layout" in r.text
    r = logged_in.post("/import/preview", files={"files": ("odd.csv", b"Foo,Bar,Baz\n1,2,3\n")})
    assert "recognise the columns" in r.text and "Foo, Bar, Baz" in r.text


def test_detects_layout_and_account_for_several_files_at_once(logged_in, db):
    card = make_account(db, "Chase card", "chase_card")
    chk = make_account(db, "Chase checking", "chase_checking", kind="checking")
    apple = make_account(db, "Apple Card", "apple_card")
    files = [
        ("files", ("Chase8393_Activity.csv", (FIX / "chase_card_a.csv").read_bytes())),
        ("files", ("Chase2630_Activity.csv", (FIX / "chase_checking.csv").read_bytes())),
        ("files", ("Apple Card Transactions.csv", (FIX / "apple_card.csv").read_bytes())),
    ]
    r = logged_in.post("/import/preview", files=files)
    assert r.status_code == 200
    import re

    picked = re.findall(r'name="account_id_(\d)".*?value="(\d+)" selected', r.text, re.S)
    assert dict(picked) == {"0": str(card.id), "1": str(chk.id), "2": str(apple.id)}
    shas = re.findall(r'name="sha_(\d)" value="([0-9a-f]+)"', r.text)
    data = {}
    for i, sha in shas:
        data[f"sha_{i}"] = sha
        data[f"filename_{i}"] = f"f{i}.csv"
        data[f"account_id_{i}"] = dict(picked)[i]
    r = logged_in.post("/import/commit", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert count(db, card.id) == 9 and count(db, chk.id) == 8 and count(db, apple.id) == 10


def test_two_accounts_same_layout_use_filename_hint(logged_in, db):
    a = make_account(db, "Chase Sapphire", "chase_card")
    b = make_account(db, "Chase Freedom", "chase_card")
    import re

    with (FIX / "chase_card_a.csv").open("rb") as f:
        r = logged_in.post("/import/preview", files={"files": ("Chase1418_Activity.csv", f)})
    assert "Two or more accounts use this layout" in r.text
    assert 'name="hint_0" value="1418"' in r.text
    sha = re.search(r'name="sha_0" value="([0-9a-f]+)"', r.text).group(1)
    r = logged_in.post(
        "/import/commit",
        data={"sha_0": sha, "filename_0": "Chase1418_Activity.csv", "account_id_0": b.id,
              "remember_0": "1", "hint_0": "1418"},
        follow_redirects=False,
    )  # fmt: skip
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Account, b.id).import_hint == "1418" and count(db, b.id) == 9
    # next time the file name decides, no question asked
    with (FIX / "chase_card_b.csv").open("rb") as f:
        r = logged_in.post("/import/preview", files={"files": ("Chase1418_Activity.csv", f)})
    assert "Two or more accounts" not in r.text
    assert re.search(rf'value="{b.id}" selected', r.text)
    assert a.id  # untouched


def test_rows_before_tracking_start_are_never_imported(logged_in, db):
    card = make_account(db, "Chase card", "chase_card")
    old = (
        b"Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        b"07/31/2026,08/01/2026,OLD SHOP,Shopping,Sale,-5.00,\n"
        b"08/01/2026,08/02/2026,NEW SHOP,Shopping,Sale,-6.00,\n"
    )
    r = logged_in.post("/import/preview", files={"files": ("Chase.csv", old)})
    assert "Before Aug 01 2026" in r.text
    import re

    sha = re.search(r'name="sha_0" value="([0-9a-f]+)"', r.text).group(1)
    logged_in.post(
        "/import/commit", data={"sha_0": sha, "filename_0": "c.csv", "account_id_0": card.id},
        follow_redirects=False,
    )  # fmt: skip
    rows = db.scalars(select(Transaction)).all()
    assert [t.description_raw for t in rows] == ["NEW SHOP"]
    imp = db.scalar(select(Import))
    assert imp.rows_skipped_old == 1 and imp.rows_total == 2


def test_changing_tracking_start_excludes_existing_rows(logged_in, db):
    card = make_account(db, "Chase card", "chase_card")
    upload(logged_in, card.id, FIX / "chase_card_a.csv")  # Sep 10 to Sep 17
    r = logged_in.post(
        "/settings/tracking-start", data={"start": "2026-09-15"}, follow_redirects=False
    )
    assert r.status_code == 303 and "Excluded 2" in (r.cookies.get("bt_flash") or "")
    db.expire_all()
    early = db.scalars(select(Transaction).where(Transaction.date < dt.date(2026, 9, 15))).all()
    assert early and all(t.is_excluded for t in early)
    assert "2026-09-15" in logged_in.get("/settings").text


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


def test_filename_hint_prefers_digits_attached_to_a_word():
    from app.importer.detect import filename_digits

    assert filename_digits("Chase8393_Activity_20260920.csv") == "8393"
    assert filename_digits("ae2a4564-Chase2630_Activity.csv") == "2630"
    assert filename_digits("Apple_Card_Transactions_Sep_01_2026.csv") is None
    assert filename_digits("statement 1418 sept.csv") == "1418"
