"""Turn a bank CSV into normalised rows using a CsvProfile."""

import csv
import datetime as dt
import io
from dataclasses import dataclass, field

from app.models import CsvProfile
from app.util import clean_description, str_to_cents

FALLBACK_DATE_FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y"]


class ParseError(Exception):
    pass


@dataclass
class ParsedRow:
    index: int  # 0-based data row number in the file
    date: dt.date
    post_date: dt.date | None
    description_raw: str
    description_clean: str
    merchant_name: str | None
    amount: int  # cents; negative = money out
    balance: int | None
    reference: str | None
    bank_category: str | None
    bank_type: str | None
    card_holder: str | None
    kind: str = "expense"
    fingerprint: str = ""
    dup_index: int = 0
    warnings: list[str] = field(default_factory=list)


def sniff_headers(data: bytes, delimiter: str = ",", skip_rows: int = 0) -> list[str]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()[skip_rows:]
    if not lines:
        return []
    return [h.strip() for h in next(csv.reader([lines[0]], delimiter=delimiter))]


def _parse_date(value: str, fmt: str) -> dt.date:
    v = value.strip()
    try:
        return dt.datetime.strptime(v, fmt).date()
    except ValueError:
        pass
    for f in FALLBACK_DATE_FORMATS:
        try:
            return dt.datetime.strptime(v, f).date()
        except ValueError:
            continue
    raise ParseError(f"Can't read date {value!r} with format {fmt}")


def _get(row: dict, col: str | None) -> str:
    if not col:
        return ""
    v = row.get(col)
    return (v or "").strip()


def parse_csv(data: bytes, profile: CsvProfile) -> list[ParsedRow]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()[profile.skip_rows :]
    if not lines:
        raise ParseError("The file is empty.")
    reader = csv.DictReader(
        io.StringIO("\n".join(lines)), delimiter=profile.delimiter or ",", restkey="_extra"
    )
    headers = [h.strip() for h in (reader.fieldnames or [])]
    reader.fieldnames = headers
    required = [profile.col_date, profile.col_description]
    if profile.col_amount:
        required.append(profile.col_amount)
    else:
        required += [c for c in (profile.col_debit, profile.col_credit) if c]
    missing = [c for c in required if c and c not in headers]
    if missing:
        raise ParseError(
            f"Columns {missing} not found. The file has: {', '.join(headers)}. "
            "Check the account's CSV profile."
        )

    out: list[ParsedRow] = []
    for i, row in enumerate(reader):
        if not any(
            (v or "").strip() for k, v in row.items() if k != "_extra" and isinstance(v, str)
        ):
            continue
        desc = _get(row, profile.col_description)
        date_s = _get(row, profile.col_date)
        if not date_s or not desc:
            continue
        d = _parse_date(date_s, profile.date_format)
        post_s = _get(row, profile.col_post_date)
        post = _parse_date(post_s, profile.date_format) if post_s else None

        if profile.col_amount:
            amt_s = _get(row, profile.col_amount)
            if not amt_s:
                continue
            amount = str_to_cents(amt_s)
        else:
            debit = _get(row, profile.col_debit)
            credit = _get(row, profile.col_credit)
            amount = -abs(str_to_cents(debit)) if debit else 0
            if credit:
                amount += abs(str_to_cents(credit))
        if profile.negate_amounts:
            amount = -amount

        bal_s = _get(row, profile.col_balance)
        balance = str_to_cents(bal_s) if bal_s else None
        merchant = _get(row, profile.col_merchant) or None
        kind = "expense" if amount < 0 else profile.positive_kind

        out.append(
            ParsedRow(
                index=i,
                date=d,
                post_date=post,
                description_raw=desc,
                description_clean=clean_description(desc),
                merchant_name=merchant,
                amount=amount,
                balance=balance,
                reference=_get(row, profile.col_reference) or None,
                bank_category=_get(row, profile.col_bank_category) or None,
                bank_type=_get(row, profile.col_bank_type) or None,
                card_holder=_get(row, profile.col_card_holder) or None,
                kind=kind,
            )
        )
    return out
