"""Review queue: uncategorised spending grouped by merchant, one action per group."""

from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.audit import log, new_batch
from app.deps import DB, CurrentUser, redirect, render
from app.models import Category, Rule, Transaction
from app.rules.engine import apply_rules
from app.util import suggest_pattern

router = APIRouter(prefix="/review")


@dataclass
class Group:
    key: str
    label: str
    pattern: str
    txns: list[Transaction] = field(default_factory=list)
    bank_categories: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(t.amount for t in self.txns)

    @property
    def bank_hint(self) -> str | None:
        if not self.bank_categories:
            return None
        return max(self.bank_categories.items(), key=lambda kv: kv[1])[0]


def _group_key(t: Transaction) -> str:
    if t.merchant_name:
        return t.merchant_name.upper()
    return suggest_pattern(t.description_clean)


def _pending(db, import_id: int | None):
    stmt = (
        select(Transaction)
        .where(
            Transaction.kind == "expense",
            Transaction.is_excluded.is_(False),
            Transaction.category_id.is_(None),
        )
        .order_by(Transaction.date.desc())
    )
    if import_id:
        stmt = stmt.where(Transaction.import_id == import_id)
    return db.scalars(stmt).all()


def build_groups(txns) -> list[Group]:
    groups: dict[str, Group] = {}
    for t in txns:
        key = _group_key(t)
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(
                key=key,
                label=t.merchant_name or t.description_clean.title(),
                pattern=suggest_pattern(t.description_clean),
            )
        g.txns.append(t)
        if t.bank_category:
            g.bank_categories[t.bank_category] = g.bank_categories.get(t.bank_category, 0) + 1
    return sorted(groups.values(), key=lambda g: (-len(g.txns), g.total))


@router.get("")
def queue(request: Request, db: DB, user: CurrentUser, import_id: int | None = None):
    txns = _pending(db, import_id)
    groups = build_groups(txns)
    cats = db.scalars(
        select(Category)
        .where(Category.is_archived.is_(False))
        .order_by(Category.group_name, Category.sort_order, Category.name)
    ).all()
    return render(
        request,
        "review/queue.html",
        groups=groups,
        count=len(txns),
        cats=cats,
        import_id=import_id,
    )


@router.post("/assign")
async def assign(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    key = str(form.get("key") or "")
    action = str(form.get("action") or "category")
    value = str(form.get("value") or "")
    make_rule = form.get("make_rule") == "1"
    import_id = str(form.get("import_id") or "")
    txns = [t for t in _pending(db, int(import_id) if import_id else None) if _group_key(t) == key]
    if not txns:
        return redirect("/review", flash="Those are already done.")
    batch = new_batch()
    rule = None
    if make_rule:
        sample = txns[0]
        rule = Rule(
            name=sample.merchant_name or sample.description_clean.title(),
            match_type="contains",
            pattern=suggest_pattern(sample.description_clean),
            priority=100,
        )
        if sample.merchant_name:
            # Apple Card gives a clean merchant; match on that too via the description haystack.
            rule.pattern = sample.merchant_name.upper()
    for t in txns:
        before = {"category_id": t.category_id, "is_excluded": t.is_excluded, "kind": t.kind}
        if action == "category" and value:
            t.category_id = int(value)
            t.category_locked = True
            if rule:
                rule.category_id = t.category_id
        elif action == "exclude":
            t.is_excluded = True
            if rule:
                rule.set_excluded = True
        elif action == "transfer":
            t.kind = "transfer"
            t.is_excluded = True
            if rule:
                rule.set_kind = "transfer"
                rule.set_excluded = True
        log(db, user.id, "transaction", t.id, "review", before=before, batch_id=batch)
    if rule and (rule.category_id or rule.set_excluded or rule.set_kind):
        db.add(rule)
        db.flush()
        # Apply the new rule to anything else uncategorised it matches.
        rest = [t for t in _pending(db, None) if t not in txns]
        apply_rules(db, rest, [rule])
    db.commit()
    back = f"/review?import_id={import_id}" if import_id else "/review"
    return redirect(back, flash=f"Done: {len(txns)} transaction{'s' if len(txns) != 1 else ''}.")
