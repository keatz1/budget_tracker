import datetime as dt

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.deps import DB, CurrentUser, redirect, render
from app.models import Account, Category, Rule, SubBudget, Transaction
from app.rules.engine import apply_rules, matches
from app.util import suggest_pattern

router = APIRouter(prefix="/rules")

MATCH_TYPES = [("contains", "contains"), ("starts_with", "starts with"), ("exact", "is exactly"),
               ("regex", "matches regex")]  # fmt: skip


@router.get("")
def list_rules(request: Request, db: DB, user: CurrentUser):
    rules = db.scalars(
        select(Rule)
        .options(joinedload(Rule.category), joinedload(Rule.account), joinedload(Rule.sub_budget))
        .order_by(Rule.priority, Rule.id)
    ).all()
    return render(request, "rules/list.html", rules=rules)


def _form(request, db, rule, error=None, prefill=None):
    cats = db.scalars(
        select(Category).where(Category.is_archived.is_(False)).order_by(Category.group_name,
                                                                          Category.name)
    ).all()  # fmt: skip
    accounts = db.scalars(select(Account).order_by(Account.name)).all()
    subs = db.scalars(select(SubBudget).order_by(SubBudget.status, SubBudget.name)).all()
    return render(
        request, "rules/form.html", rule=rule, cats=cats, accounts=accounts, subs=subs,
        match_types=MATCH_TYPES, error=error, prefill=prefill or {},
    )  # fmt: skip


@router.get("/new")
def new_form(request: Request, db: DB, user: CurrentUser, from_: int | None = None):
    prefill = {}
    src = request.query_params.get("from")
    if src and src.isdigit():
        t = db.get(Transaction, int(src))
        if t:
            prefill = {
                "name": t.merchant_name or t.description_clean.title(),
                "pattern": (t.merchant_name or suggest_pattern(t.description_clean)).upper(),
                "category_id": t.category_id,
                "account_id": t.account_id,
            }
    return _form(request, db, None, prefill=prefill)


@router.post("/run-all")
def run_all(request: Request, db: DB, user: CurrentUser):
    """Re-run every enabled rule over unlocked transactions."""
    txns = db.scalars(select(Transaction).where(Transaction.category_locked.is_(False))).all()
    n = apply_rules(db, txns)
    db.commit()
    return redirect("/rules", flash=f"Rules re-run. {n} transactions changed.")


@router.get("/test")
def test_pattern(request: Request, db: DB, user: CurrentUser):
    """HTMX: how many existing transactions would this rule hit?"""
    p = request.query_params
    rule = Rule(
        match_type=p.get("match_type") or "contains",
        pattern=(p.get("pattern") or "").strip() or None,
        bank_type_equals=(p.get("bank_type_equals") or "").strip() or None,
        account_id=int(p["account_id"]) if p.get("account_id", "").isdigit() else None,
    )
    if not rule.pattern and not rule.bank_type_equals:
        return render(request, "rules/_test.html", hits=None, sample=[])
    txns = db.scalars(select(Transaction).order_by(Transaction.date.desc())).all()
    hits = [t for t in txns if matches(rule, t)]
    return render(request, "rules/_test.html", hits=len(hits), sample=hits[:5])


@router.get("/{rule_id}")
def edit_form(request: Request, db: DB, user: CurrentUser, rule_id: int):
    rule = db.get(Rule, rule_id)
    return _form(request, db, rule) if rule else redirect("/rules")


def _apply(rule: Rule, form) -> None:
    def s(k):
        return str(form.get(k) or "").strip()

    def i(k):
        v = s(k)
        return int(v) if v.isdigit() else None

    def d(k):
        v = s(k)
        return dt.date.fromisoformat(v) if v else None

    rule.name = s("name") or None
    rule.priority = i("priority") or 100
    rule.is_enabled = bool(form.get("is_enabled"))
    rule.match_type = s("match_type") or "contains"
    rule.pattern = s("pattern") or None
    rule.bank_type_equals = s("bank_type_equals") or None
    rule.account_id = i("account_id")
    rule.date_from = d("date_from")
    rule.date_to = d("date_to")
    rule.category_id = i("category_id")
    rule.sub_budget_id = i("sub_budget_id")
    rule.merchant_name = s("merchant_name") or None
    rule.set_excluded = bool(form.get("set_excluded"))
    rule.set_kind = s("set_kind") or None


def _apply_existing(db, rule: Rule) -> int:
    txns = db.scalars(select(Transaction).where(Transaction.category_locked.is_(False))).all()
    return apply_rules(db, [t for t in txns if matches(rule, t)], [rule])


@router.post("/new")
async def create(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    rule = Rule()
    _apply(rule, form)
    if not rule.pattern and not rule.bank_type_equals:
        return _form(request, db, None, "A rule needs a pattern or a bank type to match.")
    db.add(rule)
    db.flush()
    n = _apply_existing(db, rule) if form.get("apply_existing") else 0
    db.commit()
    msg = "Rule added." + (f" Applied to {n} existing transactions." if n else "")
    return redirect("/rules", flash=msg)


@router.post("/{rule_id}")
async def update(request: Request, db: DB, user: CurrentUser, rule_id: int):
    rule = db.get(Rule, rule_id)
    if not rule:
        return redirect("/rules")
    form = await request.form()
    _apply(rule, form)
    n = _apply_existing(db, rule) if form.get("apply_existing") else 0
    db.commit()
    msg = "Saved." + (f" Applied to {n} existing transactions." if n else "")
    return redirect("/rules", flash=msg)


@router.post("/{rule_id}/delete")
def delete(request: Request, db: DB, user: CurrentUser, rule_id: int):
    rule = db.get(Rule, rule_id)
    if rule:
        db.delete(rule)
        db.commit()
    return redirect("/rules", flash="Rule deleted.")


@router.post("/{rule_id}/toggle")
def toggle(request: Request, db: DB, user: CurrentUser, rule_id: int):
    rule = db.get(Rule, rule_id)
    if rule:
        rule.is_enabled = not rule.is_enabled
        db.commit()
    return redirect("/rules")
