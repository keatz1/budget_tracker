"""Built-in CSV profiles, starter categories and default rules. Idempotent."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, CsvProfile, Rule

BUILTIN_PROFILES: list[dict] = [
    {
        "slug": "chase_card",
        "name": "Chase credit card",
        "date_format": "%m/%d/%Y",
        "col_date": "Transaction Date",
        "col_post_date": "Post Date",
        "col_description": "Description",
        "col_amount": "Amount",
        "col_bank_category": "Category",
        "col_bank_type": "Type",
        "col_reference": "Memo",
        "negate_amounts": False,
        "positive_kind": "expense",  # a positive row on a card is a refund
    },
    {
        "slug": "chase_checking",
        "name": "Chase checking",
        "date_format": "%m/%d/%Y",
        "col_date": "Posting Date",
        "col_description": "Description",
        "col_amount": "Amount",
        "col_balance": "Balance",
        "col_bank_type": "Type",
        "col_reference": "Check or Slip #",
        "negate_amounts": False,
        "positive_kind": "income",
    },
    {
        "slug": "apple_card",
        "name": "Apple Card",
        "date_format": "%m/%d/%y",
        "col_date": "Transaction Date",
        "col_post_date": "Clearing Date",
        "col_description": "Description",
        "col_merchant": "Merchant",
        "col_amount": "Amount (USD)",
        "col_bank_category": "Category",
        "col_bank_type": "Type",
        "col_card_holder": "Purchased By",
        "negate_amounts": True,
        "positive_kind": "expense",
    },
]

STARTER_CATEGORIES: list[tuple[str, str, str]] = [
    # (group, name, colour)
    ("Everyday", "Groceries", "#16a34a"),
    ("Everyday", "Restaurants", "#f97316"),
    ("Everyday", "Coffee", "#a16207"),
    ("Everyday", "Transport", "#0ea5e9"),
    ("Everyday", "Shopping", "#8b5cf6"),
    ("Home", "Household", "#64748b"),
    ("Home", "Pets", "#d946ef"),
    ("Home", "Subscriptions", "#6366f1"),
    ("Health", "Health", "#ef4444"),
    ("Fun", "Travel", "#14b8a6"),
    ("Fun", "Entertainment", "#eab308"),
    ("Fun", "Gifts", "#ec4899"),
    ("Other", "Other", "#9ca3af"),
]

DEFAULT_RULES: list[dict] = [
    # Card payments and account transfers are not spending.
    {
        "name": "Card payment (bank Type)",
        "bank_type_equals": "Payment",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 10,
    },
    {
        "name": "Account transfer (bank Type)",
        "bank_type_equals": "ACCT_XFER",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 10,
    },
    {
        "name": "Loan / card payment (bank Type)",
        "bank_type_equals": "LOAN_PMT",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 10,
    },
    {
        "name": "Payment to Chase card",
        "match_type": "contains",
        "pattern": "PAYMENT TO CHASE CARD",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 11,
    },
    {
        "name": "Apple Card payment",
        "match_type": "contains",
        "pattern": "APPLECARD GSBANK",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 11,
    },
    {
        "name": "Schwab transfer",
        "match_type": "contains",
        "pattern": "SCHWAB BANK",
        "set_kind": "transfer",
        "set_excluded": True,
        "priority": 11,
    },
    {
        "name": "Payroll",
        "match_type": "contains",
        "pattern": "PAYROLL",
        "set_kind": "income",
        "set_excluded": True,
        "priority": 12,
    },
]


def seed(db: Session) -> None:
    for p in BUILTIN_PROFILES:
        existing = db.scalar(select(CsvProfile).where(CsvProfile.slug == p["slug"]))
        if existing is None:
            db.add(CsvProfile(is_builtin=True, **p))
        else:
            for k, v in p.items():
                setattr(existing, k, v)
            existing.is_builtin = True
    if db.scalar(select(Category.id).limit(1)) is None:
        for i, (group, name, colour) in enumerate(STARTER_CATEGORIES):
            db.add(Category(name=name, group_name=group, colour=colour, sort_order=i))
    if db.scalar(select(Rule.id).limit(1)) is None:
        for r in DEFAULT_RULES:
            db.add(Rule(**r))
    db.commit()
