"""Rule matching and application. First match by priority wins."""

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Rule, Transaction
from app.models.base import utcnow


def load_rules(db: Session) -> list[Rule]:
    return list(
        db.scalars(
            select(Rule).where(Rule.is_enabled.is_(True)).order_by(Rule.priority, Rule.id)
        ).all()
    )


def _pattern_matches(rule: Rule, text: str) -> bool:
    if not rule.pattern:
        return True
    pat = rule.pattern.upper().strip()
    t = text.upper()
    if rule.match_type == "contains":
        return pat in t
    if rule.match_type == "starts_with":
        return t.startswith(pat)
    if rule.match_type == "exact":
        return t == pat
    if rule.match_type == "regex":
        try:
            return re.search(rule.pattern, text, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def matches(rule: Rule, txn: Transaction) -> bool:
    if rule.account_id and rule.account_id != txn.account_id:
        return False
    if rule.date_from and txn.date < rule.date_from:
        return False
    if rule.date_to and txn.date > rule.date_to:
        return False
    if rule.bank_type_equals and (txn.bank_type or "").upper() != rule.bank_type_equals.upper():
        return False
    if not rule.pattern and not rule.bank_type_equals:
        return False  # a rule with no matcher matches nothing
    if rule.pattern:
        hay = txn.description_clean + " " + (txn.merchant_name or "") + " " + txn.description_raw
        return _pattern_matches(rule, hay)
    return True


def first_match(rules: Iterable[Rule], txn: Transaction) -> Rule | None:
    for r in rules:
        if matches(r, txn):
            return r
    return None


def apply_rule(rule: Rule, txn: Transaction) -> bool:
    """Apply a rule's actions. Returns True if anything changed."""
    changed = False
    if rule.category_id and not txn.category_locked and txn.category_id != rule.category_id:
        txn.category_id = rule.category_id
        changed = True
    if rule.sub_budget_id and txn.sub_budget_id != rule.sub_budget_id:
        txn.sub_budget_id = rule.sub_budget_id
        changed = True
    if rule.merchant_name and txn.merchant_name != rule.merchant_name:
        txn.merchant_name = rule.merchant_name
        changed = True
    if rule.set_excluded and not txn.is_excluded:
        txn.is_excluded = True
        changed = True
    if rule.set_kind and txn.kind != rule.set_kind:
        txn.kind = rule.set_kind
        changed = True
    return changed


def apply_rules(db: Session, txns: Iterable[Transaction], rules: list[Rule] | None = None) -> int:
    """Run all enabled rules over the given transactions. Returns count changed."""
    rules = load_rules(db) if rules is None else rules
    changed = 0
    for txn in txns:
        rule = first_match(rules, txn)
        if rule is None:
            continue
        if apply_rule(rule, txn):
            changed += 1
        rule.hit_count = (rule.hit_count or 0) + 1
        rule.last_hit_at = utcnow()
    return changed
