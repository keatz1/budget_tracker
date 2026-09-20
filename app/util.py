"""Small helpers shared across the app: money, months, text cleaning."""

import calendar
import re
from datetime import date

from app.config import settings

_WS = re.compile(r"\s+")
_NOISE = re.compile(
    r"\b(?:\d{2}/\d{2}(?:/\d{2,4})?|WEB ID:\s*\S+|PPD ID:\s*\S+|TRANSACTION#:\s*\S+"
    r"|REFERENCE#:\s*\S+|#\s?\d+|\d{6,})\b",
    re.IGNORECASE,
)


def cents_to_str(cents: int | None, sign: bool = False) -> str:
    """1234 -> $12.34; -1234 -> -$12.34 (or $12.34 when sign=False on negatives)."""
    if cents is None:
        return ""
    neg = cents < 0
    whole, frac = divmod(abs(cents), 100)
    s = f"{settings.currency_symbol}{whole:,}.{frac:02d}"
    if sign and neg:
        return f"-{s}"
    if sign and cents > 0:
        return f"+{s}"
    return s


def str_to_cents(text: str) -> int:
    """'1,234.56' -> 123456. '-9.44' -> -944. '(12.00)' -> -1200."""
    t = text.strip().replace(",", "").replace(settings.currency_symbol, "")
    if not t:
        raise ValueError("empty amount")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t.startswith("-"):
        neg, t = True, t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if "." in t:
        whole, frac = t.split(".", 1)
        frac = (frac + "00")[:2]
    else:
        whole, frac = t, "00"
    cents = int(whole or "0") * 100 + int(frac)
    return -cents if neg else cents


def clean_description(raw: str) -> str:
    """Upper-case, strip reference numbers and dates, collapse whitespace."""
    s = raw.upper()
    s = _NOISE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9*&'./ -]", " ", s)
    return _WS.sub(" ", s).strip()


def suggest_pattern(description_clean: str) -> str:
    """A rule pattern from a cleaned description: first two or three tokens."""
    tokens = [t for t in description_clean.split() if not t.isdigit()]
    return " ".join(tokens[:3]) if tokens else description_clean


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def shift_month(month: str, delta: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_label(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{calendar.month_abbr[m]} {y}"


def months_between(start: str, end: str) -> list[str]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = shift_month(cur, 1)
    return out


def this_month() -> str:
    return month_key(date.today())
