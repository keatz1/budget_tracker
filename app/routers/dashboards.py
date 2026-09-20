import json

from fastapi import APIRouter, Request

from app.deps import DB, CurrentUser, render
from app.reports.service import (
    OTHER_COLOUR,
    all_series,
    monthly_totals,
    spend_by_holder,
    top_categories,
    top_merchants,
    uncategorised_by_month,
)
from app.util import month_label, months_between, shift_month, this_month

router = APIRouter(prefix="/dashboards")


@router.get("")
def dashboards(
    request: Request,
    db: DB,
    user: CurrentUser,
    month: str | None = None,
    category_id: int | None = None,
):
    end = month or this_month()
    start = shift_month(end, -11)
    months = months_between(start, end)
    labels = [month_label(m) for m in months]
    cats, series = all_series(db, end)
    uncat = uncategorised_by_month(db, start, end)
    totals = monthly_totals(db, months, series, uncat)

    top, rest = top_categories(cats, series, months)
    stacked = [
        {
            "label": c.name,
            "colour": c.colour,
            "data": [series[c.id][m].spent / 100 if m in series[c.id] else 0 for m in months],
        }
        for c in top
    ]
    other = [
        sum(series[c.id][m].spent for c in rest if m in series[c.id]) + uncat.get(m, 0)
        for m in months
    ]
    if any(other):
        stacked.append({"label": "Other", "colour": OTHER_COLOUR, "data": [o / 100 for o in other]})

    focus = next((c for c in cats if c.id == category_id), None) or (top[0] if top else None)
    focus_data = None
    if focus:
        st = series[focus.id]
        focus_data = {
            "name": focus.name,
            "colour": focus.colour,
            "spent": [st[m].spent / 100 if m in st else 0 for m in months],
            "available": [st[m].available / 100 if m in st else None for m in months],
            "budget": [st[m].budget / 100 if m in st else None for m in months],
        }

    share = sorted(
        (
            (c.name, c.colour, series[c.id][end].spent)
            for c in cats
            if end in series[c.id] and series[c.id][end].spent > 0
        ),
        key=lambda r: -r[2],
    )
    if uncat.get(end):
        share.append(("Uncategorised", OTHER_COLOUR, uncat[end]))

    merchants_month = top_merchants(db, end, end)
    merchants_year = top_merchants(db, start, end)
    holders = spend_by_holder(db, start, end)

    year_start = end[:4] + "-01"
    ytd_months = [m for m in months_between(year_start, end)]
    ytd = monthly_totals(db, ytd_months, series, uncategorised_by_month(db, year_start, end))
    ytd_budget = sum(t.budget for t in ytd)
    ytd_spent = sum(t.spent for t in ytd)

    chart = {
        "labels": labels,
        "months": months,
        "totals": {
            "budget": [t.budget / 100 for t in totals],
            "spent": [t.spent / 100 for t in totals],
        },
        "stacked": stacked,
        "focus": focus_data,
        "share": [{"label": n, "colour": c, "value": v / 100} for n, c, v in share],
        "merchantsMonth": [
            {"label": n, "value": v / 100, "count": k} for n, v, k in merchants_month
        ],
        "merchantsYear": [{"label": n, "value": v / 100, "count": k} for n, v, k in merchants_year],
        "holders": [
            {"label": h.split(" ")[0], "data": [d.get(m, 0) / 100 for m in months]}
            for h, d in sorted(holders.items())
        ],
    }
    return render(
        request,
        "dashboards/index.html",
        month=end,
        prev_month=shift_month(end, -1),
        next_month=shift_month(end, 1),
        cats=cats,
        focus=focus,
        totals=totals,
        share=share,
        merchants_month=merchants_month,
        merchants_year=merchants_year,
        stacked=stacked,
        months=months,
        labels=labels,
        holders=holders,
        ytd_budget=ytd_budget,
        ytd_spent=ytd_spent,
        ytd_months=len(ytd_months),
        chart=json.dumps(chart),
    )
