import pytest

from app.util import (
    cents_to_str,
    clean_description,
    month_bounds,
    months_between,
    shift_month,
    str_to_cents,
    suggest_pattern,
)


@pytest.mark.parametrize(
    "text,cents",
    [("1,234.56", 123456), ("-9.44", -944), ("(12.00)", -1200), ("5", 500), ("0.2", 20),
     ("+3.10", 310), ("$1,100", 110000)],
)  # fmt: skip
def test_str_to_cents(text, cents):
    assert str_to_cents(text) == cents


def test_cents_to_str():
    assert cents_to_str(123456) == "$1,234.56"
    assert cents_to_str(-944, sign=True) == "-$9.44"
    assert cents_to_str(-944) == "$9.44"
    assert cents_to_str(500, sign=True) == "+$5.00"


def test_clean_description_strips_noise():
    assert clean_description("APPLECARD GSBANK PAYMENT    78683581        WEB ID: 9999999999") == (
        "APPLECARD GSBANK PAYMENT"
    )
    assert clean_description("Payment to Chase card ending in 8393 08/17") == (
        "PAYMENT TO CHASE CARD ENDING IN 8393"
    )
    assert clean_description("COSTA COFFEE 43011140") == "COSTA COFFEE"
    assert suggest_pattern(clean_description("TST-The Paint Room")) == "TST-THE PAINT ROOM"


def test_months():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2026-12", 1) == "2027-01"
    assert months_between("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    lo, hi = month_bounds("2026-02")
    assert lo.day == 1 and hi.day == 28
