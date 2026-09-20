# Household Budget Tracker: Build Plan

A self-hosted budget tracker for two people. Runs on a laptop today, on a Raspberry Pi later. Reachable by IP on the home network. Simpler than PocketGuard: import bank CSVs, sort transactions into categories, set monthly budgets that roll over, and see where the money went.

## 1. Decisions

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Fast to build, good CSV tooling, runs fine on a Pi |
| Web framework | FastAPI + Jinja2 templates + HTMX | Server-rendered pages, no JS build step, fast on a Pi |
| Database | SQLite (WAL mode) via SQLAlchemy 2 + Alembic | One file to back up, zero admin, plenty for two users |
| Charts | Chart.js (vendored, no CDN) | Works offline on the LAN |
| Auth | Session cookies, argon2 password hashes | Two users, no OAuth needed |
| Packaging | Docker image (multi-arch: amd64 + arm64) + docker compose | Same image on the laptop and the Pi |
| Remote access | Tailscale (recommended) or WireGuard | No port forwarding, no exposing the Pi to the internet |
| Money | Integer pence, GBP default | No float rounding |
| Tests | pytest, coverage on the import and rollover logic | These two are where bugs hurt |
| CI | GitHub Actions: ruff, mypy, pytest, docker build | Catch breakage before it reaches the Pi |

Why not a JS SPA: it doubles the code, needs a build step, and the Pi has to serve it. HTMX gives the interactivity this app needs (inline edit, filter, category dropdowns) with almost no client code.

Why not Postgres: it's another service to run and back up. SQLite handles this load with room to spare. If it ever matters, SQLAlchemy makes the swap cheap.

## 2. Data model

All money columns are integers in pence. Expenses are negative, income positive.

```
users            id, email, display_name, password_hash, is_admin, created_at
accounts         id, name, institution, kind (current|credit|savings), csv_profile_id, is_archived
csv_profiles     id, name, delimiter, has_header, skip_rows, date_format,
                 col_date, col_description, col_amount | (col_debit, col_credit),
                 col_balance, col_reference, negate_amounts
imports          id, account_id, user_id, filename, file_sha256, imported_at,
                 rows_total, rows_new, rows_duplicate, rows_flagged, undone_at
transactions     id, account_id, import_id, date, description_raw, description_clean,
                 merchant_name, amount, kind (expense|income|transfer),
                 category_id, is_excluded, notes, fingerprint (unique per account),
                 source (import|manual|split), parent_id, created_by, created_at, updated_at
categories       id, name, group_name, kind (expense|income), colour, sort_order,
                 rollover_mode (none|carry_all|carry_positive_only), rollover_cap, is_archived
budgets          id, category_id, month (YYYY-MM), amount        -- one row per category per month
                 (a category also has a default_budget; a budgets row overrides it)
rules            id, match_type (contains|starts_with|exact|regex), pattern, priority,
                 category_id, merchant_name, set_excluded, set_kind, hit_count, last_hit_at
audit_log        id, user_id, at, entity, entity_id, action, before_json, after_json
```

## 3. The hard parts

### 3.1 CSV import and dedupe

Every bank exports a different CSV. The app keeps a `csv_profile` per account that says which column is what. Ship profiles for the common UK banks (Monzo, Starling, Barclays, HSBC, Lloyds, Nationwide, NatWest, Santander, Amex) and let the user build one in the UI by uploading a sample and picking columns from dropdowns.

Import flow:

1. Upload file. Hash it. If the same file hash was imported before, say so and stop.
2. Parse with the account's profile. Normalise: trim, collapse whitespace, upper-case, strip card numbers and reference noise from the description.
3. Compute a fingerprint per row:
   `sha256(account_id | date | amount | normalised_description | balance_after if present | n)`
   where `n` is the occurrence index for identical rows on the same day (two coffees, same price, same shop).
4. Split rows into three buckets:
   - **new**: fingerprint not seen
   - **duplicate**: fingerprint seen, skip silently
   - **flagged**: not an exact duplicate but there's an existing transaction in the same account within 3 days with the same amount and a different description. This catches pending → posted description changes. Show these side by side and let the user pick keep or skip.
5. Show a preview page: counts, the flagged pairs, and the first 20 new rows with the category the rules engine would assign.
6. Commit. Run rules on the new rows. Record the import.
7. **Undo import**: deletes the transactions from that import (unless edited since, in which case warn).

### 3.2 Rules engine

Rules are ordered by priority. First match wins. A rule can set category, a clean merchant name, mark as excluded, or mark as transfer.

- Rules are created from the transaction page: "always put this in Groceries". The app pre-fills the pattern by stripping dates and reference numbers from the description.
- "Apply to existing" checkbox re-runs the rule over past uncategorised transactions.
- A rule's hit count and last hit are shown so dead rules can be pruned.
- Transactions edited by hand get a `category_locked` flag so a rule re-run never overwrites a manual choice.

### 3.3 Rollover

For each category with rollover on, the available amount in month M is:

```
available(M) = budget(M) + carry(M)
carry(M)     = clamp(available(M-1) - spent(M-1))
```

`clamp` depends on the category's mode:

- `none`: carry is always 0
- `carry_all`: overspend last month reduces this month
- `carry_positive_only`: unspent carries forward, overspend is forgiven

Optional `rollover_cap` stops a category building an unbounded pot. Rollover starts from the first month the category has a budget. Computed on the fly, month by month from the anchor; cache in a `month_summary` table only if it gets slow, which it won't for a few years of data.

### 3.4 Transfers

Moving money between your own accounts isn't spending. Rules can mark a transaction as `transfer`, and transfers are excluded from every spend figure. Later: auto-detect matching pairs (same amount, opposite sign, within 2 days, different accounts) and offer to link them.

## 4. Screens

1. **Login**
2. **This month** (home): the key number ("left to spend" = income this month − budgets not yet spent − unbudgeted spend), then a bar per category: budgeted + carry, spent, remaining. Red if over. Click through to transactions.
3. **Transactions**: filterable table (account, month, category, uncategorised, excluded, search). Inline category dropdown. Add manual transaction (income or expense) button.
   **Bulk edit** is a first-class requirement: checkbox per row, select all in current filter, then one action bar for set category, exclude/include, mark as transfer, add tag, delete, or create a rule from the selection. Filter to "Uncategorised, contains TESCO", select all, set Groceries, tick "make this a rule". Every bulk change writes one audit row per transaction and offers a single undo.
4. **Review queue**: uncategorised and flagged transactions since last visit. This is the page you open after an import.
5. **Import**: pick account, upload, preview, commit. Import history with undo.
6. **Categories & budgets**: grid of categories by group with default budget, this month's override, rollover mode. "Copy last month's budgets" button.
7. **Rules**: list, edit, reorder, hit counts, test a pattern against existing transactions.
8. **Accounts**: add, archive, pick or build a CSV profile.
9. **Dashboards**:
   - Total spend, month over month, last 12 months (bar), with income line
   - Spend by category, month over month (stacked bar, toggle to lines)
   - One category over time with its budget line
   - Category share this month (donut)
   - Top merchants this month and last 12 months
   - Net cashflow and savings rate per month
   - Year to date vs budget
10. **Settings**: users (invite, reset password), currency, backup now, export all as CSV.

Every page works on a phone. Both of you will use it from the sofa.

## 5. Features you didn't list but will want

- **Review queue after import** (above). Without it, uncategorised transactions pile up silently.
- **Transfers** (above). Without it, paying off the credit card looks like a £900 expense.
- **Import preview and undo.** The first few imports will go wrong while the CSV profile is being tuned.
- **Split transactions.** One Amazon order, two categories.
- **Category locking.** A manual categorisation must survive rule re-runs.
- **Multiple accounts.** Joint current account, two personal accounts, a credit card. Each has its own CSV format.
- **Notes and tags** on a transaction. "Birthday present for Mum."
- **Audit log.** Who changed what. Useful in a shared household when a transaction moves.
- **Nightly backup.** A cron in the container copies the SQLite file to a `backups/` volume and keeps 30 days. You can point that at a USB stick or a synced folder. The dashboards are worthless if the Pi's SD card dies with the only copy.
- **CSV export** of everything. Your data, your way out.
- **Recurring detection** (later). Flag transactions that show up monthly with the same merchant and near-same amount, so bills are known before they arrive.
- **Annual budgets** (later). Car insurance is once a year. Rollover with a cap covers most of this; a per-year budget type covers the rest.
- **Dark mode.** Cheap with CSS variables; do it from the start.

Out of scope on purpose: bank API connections (Open Banking needs a registered provider), savings goals, investment tracking, multi-currency, push notifications.

## 6. Build phases

Each phase ends with something usable and pushed.

**Phase 0: Scaffold** (½ day)
Repo layout, `pyproject.toml`, FastAPI app with a health route, SQLite + Alembic, Dockerfile, compose file, GitHub Actions running ruff/mypy/pytest. `make dev` runs it on the laptop at `http://localhost:8000`.

**Phase 1: Users and accounts** (1 day)
Login, sessions, first-run admin setup, invite second user. Accounts CRUD. Base layout, nav, dark mode.

**Phase 2: CSV import** (2 days)
CSV profiles with built-ins and the column-picker UI. Parser, normaliser, fingerprinting, three-bucket dedupe, preview, commit, undo. This phase gets the most tests: fixture CSVs from each supported bank, re-import produces zero new rows, overlapping exports dedupe correctly, pending → posted gets flagged.

**Phase 3: Transactions and categories** (1½ days)
Categories with groups. Transactions table with filters, inline category edit, exclude, manual add (income and expense), delete, transfers, notes. Bulk edit with select-all-in-filter, the action bar, and undo.

**Phase 4: Rules** (1 day)
Rules CRUD, "create rule from this transaction", apply-to-existing, category locking, review queue page, rules run at import commit.

**Phase 5: Budgets and rollover** (1 day)
Default and per-month budgets, copy last month, rollover modes and cap, the "this month" home page with left-to-spend and per-category bars. Rollover logic gets table-driven tests.

**Phase 6: Dashboards** (1½ days)
The seven charts above. One SQL query module that returns month × category aggregates; every chart reads from it. Vendored Chart.js.

**Phase 7: Pi deployment** (½ day)
Multi-arch image pushed to GitHub Container Registry. `docker compose up -d` on the Pi with `restart: unless-stopped`. Volume for the DB and backups. Nightly backup cron. Tailscale setup notes. Optional Caddy for HTTPS on a `.local` name.

**Phase 8: Polish** (ongoing)
Splits, recurring detection, transfer pairing, annual budgets, CSV export, search.

Total to a daily-use app: about 9 working days through Phase 7.

## 7. Repo layout

```
budget_tracker/
  app/
    main.py              FastAPI app, routers, middleware
    config.py            env-driven settings
    db.py                engine, session, migrations hook
    models/              SQLAlchemy models, one file per table group
    auth/                login, sessions, password hashing
    importer/            profiles, parser, normaliser, fingerprint, dedupe
    rules/               matcher, apply, suggest-pattern
    budgets/             rollover maths, month summaries
    reports/             aggregate queries feeding dashboards
    routers/             one file per screen
    templates/           Jinja2, one folder per screen + partials for HTMX
    static/              CSS, vendored Chart.js and HTMX
  alembic/
  tests/
    fixtures/csv/        one sample per bank profile
  Dockerfile
  docker-compose.yml
  Makefile
  .github/workflows/ci.yml
```

## 8. Running it

Laptop, today:

```
git clone <repo> && cd budget_tracker
cp .env.example .env
docker compose up -d
open http://localhost:8000
```

Pi, later:

```
curl -fsSL https://get.docker.com | sh
git clone <repo> && cd budget_tracker
cp .env.example .env
docker compose up -d
```

Then from any device on the LAN: `http://<pi-ip>:8000`. Install Tailscale on the Pi and your phones and the same URL works from anywhere, with no port forwarding.

## 9. Questions to settle before Phase 2

1. Which banks and cards will you import from? I'll build and test those profiles first.
2. Currency is GBP. Correct?
3. Rollover default: forgive overspend (`carry_positive_only`) or carry it (`carry_all`)? I'd default to `carry_all` and let you flip it per category.
4. Do you and your wife want separate logins with an audit trail, or one shared login? Separate is one extra table and worth it.
5. Should "left to spend" count income actually received this month, or a fixed expected monthly income you set once? PocketGuard uses expected. I'd offer both and default to expected.
