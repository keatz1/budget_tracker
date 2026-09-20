from typing import Annotated

from fastapi import APIRouter, Form, Request
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from app.deps import DB, CurrentUser, redirect, render
from app.models import Category, Transaction
from app.util import str_to_cents

router = APIRouter(prefix="/categories")

ROLLOVER_MODES = [
    ("carry_all", "Carry everything (overspend reduces next month)"),
    ("carry_positive_only", "Carry only what's left (overspend forgiven)"),
    ("none", "No rollover"),
]


@router.get("")
def list_categories(request: Request, db: DB, user: CurrentUser):
    cats = db.scalars(
        select(Category).order_by(Category.is_archived, Category.group_name, Category.sort_order)
    ).all()
    counts: dict[int | None, int] = {
        cid: n
        for cid, n in db.execute(
            select(Transaction.category_id, func.count()).group_by(Transaction.category_id)
        )
    }
    return render(request, "categories/list.html", cats=cats, counts=counts)


def _form(request, db, cat, error=None):
    groups = sorted({g for (g,) in db.execute(select(Category.group_name).distinct()) if g})
    return render(
        request, "categories/form.html", cat=cat, groups=groups, modes=ROLLOVER_MODES, error=error
    )


@router.get("/new")
def new_form(request: Request, db: DB, user: CurrentUser):
    return _form(request, db, None)


@router.get("/{cat_id}")
def edit_form(request: Request, db: DB, user: CurrentUser, cat_id: int):
    cat = db.get(Category, cat_id)
    return _form(request, db, cat) if cat else redirect("/categories")


def _apply(cat: Category, form) -> None:
    cat.name = str(form.get("name") or "").strip()
    cat.group_name = str(form.get("group_name") or "").strip() or None
    cat.kind = str(form.get("kind") or "expense")
    cat.colour = str(form.get("colour") or "#6b7280")
    cat.default_budget = abs(str_to_cents(str(form.get("default_budget") or "0")))
    cat.rollover_mode = str(form.get("rollover_mode") or "carry_all")
    cap = str(form.get("rollover_cap") or "").strip()
    cat.rollover_cap = abs(str_to_cents(cap)) if cap else None
    cat.rollover_start = str(form.get("rollover_start") or "").strip() or None
    cat.is_archived = bool(form.get("is_archived"))
    so = str(form.get("sort_order") or "0")
    cat.sort_order = int(so) if so.lstrip("-").isdigit() else 0


@router.post("/new")
async def create(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    cat = Category()
    _apply(cat, form)
    if not cat.name:
        return _form(request, db, None, "Name is required.")
    db.add(cat)
    db.commit()
    back = str(form.get("back") or "/categories")
    return redirect(back, flash=f"Added {cat.name}.")


@router.post("/{cat_id}")
async def update(request: Request, db: DB, user: CurrentUser, cat_id: int):
    cat = db.get(Category, cat_id)
    if not cat:
        return redirect("/categories")
    form = await request.form()
    _apply(cat, form)
    db.commit()
    return redirect("/categories", flash="Saved.")


@router.post("/{cat_id}/delete")
def delete(
    request: Request, db: DB, user: CurrentUser, cat_id: int,
    move_to: Annotated[str, Form()] = "",
):  # fmt: skip
    cat = db.get(Category, cat_id)
    if cat:
        target = int(move_to) if move_to else None
        db.execute(
            sa_update(Transaction)
            .where(Transaction.category_id == cat.id)
            .values(category_id=target)
        )
        db.delete(cat)
        db.commit()
    return redirect("/categories", flash="Deleted.")
