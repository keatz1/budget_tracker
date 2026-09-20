"""All tables. Money is integer cents. Expenses negative, income positive."""

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class CsvProfile(Base):
    """Which column is what in a bank's CSV export. Columns are header names."""

    __tablename__ = "csv_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str | None] = mapped_column(String(50), unique=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    delimiter: Mapped[str] = mapped_column(String(1), default=",")
    skip_rows: Mapped[int] = mapped_column(Integer, default=0)
    date_format: Mapped[str] = mapped_column(String(20), default="%m/%d/%Y")
    col_date: Mapped[str] = mapped_column(String(100))
    col_post_date: Mapped[str | None] = mapped_column(String(100))
    col_description: Mapped[str] = mapped_column(String(100))
    col_merchant: Mapped[str | None] = mapped_column(String(100))
    col_amount: Mapped[str | None] = mapped_column(String(100))
    col_debit: Mapped[str | None] = mapped_column(String(100))
    col_credit: Mapped[str | None] = mapped_column(String(100))
    col_balance: Mapped[str | None] = mapped_column(String(100))
    col_reference: Mapped[str | None] = mapped_column(String(100))
    col_bank_category: Mapped[str | None] = mapped_column(String(100))
    col_bank_type: Mapped[str | None] = mapped_column(String(100))
    col_card_holder: Mapped[str | None] = mapped_column(String(100))
    negate_amounts: Mapped[bool] = mapped_column(Boolean, default=False)
    # What a positive amount means after sign normalisation: card refunds are
    # "expense" (negative spend); a checking-account credit is "income".
    positive_kind: Mapped[str] = mapped_column(String(10), default="expense")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    institution: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="credit")  # checking|credit|savings
    csv_profile_id: Mapped[int | None] = mapped_column(ForeignKey("csv_profiles.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    csv_profile: Mapped[CsvProfile | None] = relationship()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    group_name: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="expense")  # expense|income
    colour: Mapped[str] = mapped_column(String(7), default="#6b7280")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    default_budget: Mapped[int] = mapped_column(Integer, default=0)
    rollover_mode: Mapped[str] = mapped_column(String(20), default="carry_all")
    rollover_cap: Mapped[int | None] = mapped_column(Integer)
    rollover_start: Mapped[str | None] = mapped_column(String(7))  # YYYY-MM
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    amount: Mapped[int] = mapped_column(Integer)


class SubBudget(Base):
    __tablename__ = "sub_budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    total_amount: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active|closed
    notes: Mapped[str | None] = mapped_column(Text)

    category: Mapped[Category] = relationship()


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_flagged: Mapped[int] = mapped_column(Integer, default=0)
    undone_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    account: Mapped[Account] = relationship()
    user: Mapped[User] = relationship()


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("imports.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    post_date: Mapped[dt.date | None] = mapped_column(Date)
    description_raw: Mapped[str] = mapped_column(Text)
    description_clean: Mapped[str] = mapped_column(Text)
    merchant_name: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10), default="expense")  # expense|income|transfer
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    category_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    sub_budget_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_budgets.id", ondelete="SET NULL"), index=True
    )
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    bank_category: Mapped[str | None] = mapped_column(String(100))
    bank_type: Mapped[str | None] = mapped_column(String(50))
    card_holder: Mapped[str | None] = mapped_column(String(100))
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(10), default="import")  # import|manual|split
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    sub_budget: Mapped[SubBudget | None] = relationship()

    @property
    def is_spend(self) -> bool:
        return self.kind == "expense" and not self.is_excluded


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # match
    match_type: Mapped[str] = mapped_column(String(15), default="contains")
    pattern: Mapped[str | None] = mapped_column(String(255))
    bank_type_equals: Mapped[str | None] = mapped_column(String(50))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    date_from: Mapped[dt.date | None] = mapped_column(Date)
    date_to: Mapped[dt.date | None] = mapped_column(Date)
    # actions
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    sub_budget_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_budgets.id", ondelete="SET NULL")
    )
    merchant_name: Mapped[str | None] = mapped_column(String(200))
    set_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    set_kind: Mapped[str | None] = mapped_column(String(10))
    # stats
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    category: Mapped[Category | None] = relationship()
    sub_budget: Mapped[SubBudget | None] = relationship()
    account: Mapped[Account | None] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)

    user: Mapped[User | None] = relationship()
