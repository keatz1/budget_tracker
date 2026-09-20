"""By-group view: totals per group and a tracker per category for one month."""

from dataclasses import dataclass, field

from fastapi import APIRouter, Request

from app.budgets.service import CategoryMonth, month_summary
from app.budgets.tracker import Tracker, group_total
from app.deps import DB, CurrentUser, render
from app.util import shift_month, this_month

router = APIRouter(prefix="/groups")


@dataclass
class GroupView:
    name: str
    rows: list[tuple[CategoryMonth, Tracker]] = field(default_factory=list)

    @property
    def total(self) -> Tracker:
        return group_total([t for _, t in self.rows])


@router.get("")
def by_group(
    request: Request, db: DB, user: CurrentUser, month: str | None = None, group: str | None = None
):
    month = month or this_month()
    s = month_summary(db, month)
    groups: dict[str, GroupView] = {}
    for cm in s.rows:
        st = cm.state
        if not (st.budget or st.carry or st.spent):
            continue
        name = cm.category.group_name or "Other"
        groups.setdefault(name, GroupView(name=name)).rows.append(
            (cm, Tracker(budget=st.budget, carry=st.carry, spent=st.spent))
        )
    names = list(groups)
    shown = [groups[group]] if group in groups else list(groups.values())
    return render(
        request,
        "groups/index.html",
        month=month,
        prev_month=shift_month(month, -1),
        next_month=shift_month(month, 1),
        names=names,
        group=group if group in groups else None,
        groups=shown,
        all_total=group_total([g.total for g in groups.values()]),
    )
