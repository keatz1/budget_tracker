"""Shared transaction filtering used by the list page, bulk edit and review."""

from dataclasses import dataclass

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import joinedload

from app.models import Transaction
from app.util import month_bounds

SHOW_OPTIONS = [
    ("spend", "Spending"),
    ("all", "Everything"),
    ("uncat", "Uncategorised"),
    ("excluded", "Excluded"),
    ("transfer", "Transfers"),
    ("income", "Income"),
]


@dataclass
class TxnFilter:
    month: str | None = None  # YYYY-MM, or None for all time
    show: str = "spend"
    account_id: int | None = None
    category_id: int | None = None
    sub_budget_id: int | None = None
    card_holder: str | None = None
    q: str | None = None
    import_id: int | None = None

    @classmethod
    def from_params(cls, p) -> "TxnFilter":
        def _int(name):
            v = p.get(name)
            return int(v) if v and v.isdigit() else None

        month = p.get("month") or None
        if month == "all":
            month = None
        return cls(
            month=month,
            show=p.get("show") or "spend",
            account_id=_int("account_id"),
            category_id=_int("category_id"),
            sub_budget_id=_int("sub_budget_id"),
            card_holder=p.get("card_holder") or None,
            q=(p.get("q") or "").strip() or None,
            import_id=_int("import_id"),
        )

    def as_params(self) -> dict[str, str]:
        out = {"month": self.month or "all", "show": self.show}
        for k in ("account_id", "category_id", "sub_budget_id", "card_holder", "q", "import_id"):
            v = getattr(self, k)
            if v not in (None, ""):
                out[k] = str(v)
        return out

    def apply(self, stmt: Select) -> Select:
        T = Transaction
        if self.month:
            lo, hi = month_bounds(self.month)
            stmt = stmt.where(T.date >= lo, T.date <= hi)
        if self.show == "spend":
            stmt = stmt.where(T.kind == "expense", T.is_excluded.is_(False))
        elif self.show == "uncat":
            stmt = stmt.where(
                T.kind == "expense", T.is_excluded.is_(False), T.category_id.is_(None)
            )
        elif self.show == "excluded":
            stmt = stmt.where(T.is_excluded.is_(True))
        elif self.show == "transfer":
            stmt = stmt.where(T.kind == "transfer")
        elif self.show == "income":
            stmt = stmt.where(T.kind == "income")
        if self.account_id:
            stmt = stmt.where(T.account_id == self.account_id)
        if self.category_id:
            stmt = stmt.where(T.category_id == self.category_id)
        if self.sub_budget_id:
            stmt = stmt.where(T.sub_budget_id == self.sub_budget_id)
        if self.card_holder:
            stmt = stmt.where(T.card_holder == self.card_holder)
        if self.import_id:
            stmt = stmt.where(T.import_id == self.import_id)
        if self.q:
            like = f"%{self.q}%"
            stmt = stmt.where(
                or_(
                    T.description_raw.ilike(like),
                    T.merchant_name.ilike(like),
                    T.notes.ilike(like),
                )
            )
        return stmt


def txn_select() -> Select:
    return select(Transaction).options(
        joinedload(Transaction.category),
        joinedload(Transaction.account),
        joinedload(Transaction.sub_budget),
    )
