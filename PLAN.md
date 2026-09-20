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
| Money | Integer cents, USD | No float rounding. Foreign spend is already converted by the card issuer |
| Tests | pytest, coverage on the import and rollover logic | These two are where bugs hurt |
| CI | GitHub Actions: ruff, mypy, pytest, docker build | Catch breakage before it reaches the Pi |

Why not a JS SPA: it doubles the code, needs a build step, and the Pi has to serve it. HTMX gives the interactivity this app needs (inline edit, filter, category dropdowns) with almost no client code.

Why not Postgres: it's another service to run and back up. SQLite handles this load with room to spare. If it ever matters, SQLAlchemy makes the swap cheap.

## 2. Data model

All money columns are integers in cents. Expenses are negative, income positive, whatever sign the bank used.

```
users            id, email, display_name, password_hash, is_admin, created_at
accounts         id, name, institution, kind (current|credit|savings), csv_profile_id, is_archived
csv_profiles     id, name, delimiter, has_header, skip_rows, date_format,
                 col_date, col_description, col_amount | (col_debit, col_credit),
                 col_balance, col_reference, negate_amounts
imports          id, account_id, user_id, filename, file_sha256, imported_at,
                 rows_total, rows_new, rows_duplicate, rows_flagged, undone_at
transactions     id, account_id, import_id, date, post_date, description_raw, description_clean,
                 merchant_name, amount, kind (expense|income|transfer),
                 category_id, category_locked, sub_budget_id, is_excluded, notes,
                 bank_category, bank_type, card_holder,
                 fingerprint (unique per account), source (import|manual|split), parent_id,
                 created_by, created_at, updated_at
categories       id, name, group_name, kind (expense|income), colour, sort_order,
                 rollover_mode (none|carry_all|carry_positive_only), rollover_cap, is_archived
budgets          id, category_id, month (YYYY-MM), amount        -- one row per category per month
                 (a category also has a default_budget; a budgets row overrides it)
sub_budgets      id, category_id, name, total_amount, start_date, end_date (nullable),
                 status (active|closed), notes
rules            id, match_type (contains|starts_with|exact|regex), pattern, priority,
                 account_id (nullable), date_from, date_to (nullable),
                 category_id, sub_budget_id, merchant_name, set_excluded, set_kind,
                 hit_count, last_hit_at
audit_log        id, user_id, at, entity, entity_id, action, before_json, after_json
```

## 3. The hard parts

### 3.1 CSV import and dedupe

Every bank exports a different CSV. The app keeps a `csv_profile` per account that says which column is what. Three profiles ship on day one, built from your real exports:

| Profile | Columns | Sign | Quirks |
|---|---|---|---|
| Chase credit card | Transaction Date, Post Date, Description, Category, Type, Amount, Memo | negative = spend | No balance, no reference. `Type` is Sale, Payment, or Return. Payment → transfer |
| Chase checking | Details, Posting Date, Description, Amount, Type, Balance, Check or Slip # | negative = debit | Header has 7 columns, every row has 8 (trailing comma). Parser must tolerate. `Type` values like ACH_DEBIT, ACCT_XFER, LOAN_PMT, QUICKPAY_CREDIT feed the transfer rule. `Balance` goes into the fingerprint |
| Apple Card | Transaction Date, Clearing Date, Description, Merchant, Category, Type, Amount (USD), Purchased By | positive = purchase | `negate_amounts` on. `Merchant` is already clean, use it. `Purchased By` → `card_holder`. `Type` Payment → transfer |

Dates are `M/D/YY` (Apple) and `MM/DD/YYYY` (Chase). The profile stores the format.

The bank's own `Category` column is kept as `bank_category`. It's a hint, not truth: when no rule matches, the review queue shows it as the suggested category and one click accepts. Over time your rules replace it.

`Purchased By` on the Apple Card means the dashboards can split spend by person for free. Chase doesn't give this, so it's a filter where present, not a core feature.

The column-picker UI for new profiles (upload a sample, map columns from dropdowns) still gets built, for the next card you open.

**The overlapping-export case is the whole point.** You'll export a running list from each bank, say the last 90 days, every week or two. Most rows in each export were already imported last time. The importer must add only the rows it hasn't seen and leave everything else alone, including any category or note you've set on the old rows. It never updates or deletes an existing transaction from an import. The unique fingerprint index on `transactions` enforces this at the database level, not just in code.

Import flow:

1. Upload file. Hash it. If the same file hash was imported before, say so and stop.
2. Parse with the account's profile. Normalise: trim, collapse whitespace, upper-case, strip card numbers and reference noise from the description.
3. Compute a fingerprint per row:
   `sha256(account_id | transaction_date | post_date | amount | normalised_description | balance_after if present | n)`
   where `n` is the occurrence index for identical rows on the same day. Your Apple Card export has twenty-two identical `BELBIM AS. ULASIM` rows at $1.35 across three days; this is what `n` is for. Chase checking has a running balance, which makes its fingerprints unambiguous. The Chase card has neither balance nor reference, so date, post date, amount, description and `n` are all it gets, and that's enough as long as exports are taken after transactions post.
4. Split rows into three buckets:
   - **new**: fingerprint not seen
   - **duplicate**: fingerprint seen, skip silently. On a routine re-export this is most of the file
   - **flagged**: not an exact duplicate but there's an existing transaction in the same account within 3 days with the same amount and a different description. This catches pending → posted description changes. Show these side by side and let the user pick keep or skip.
5. Show a preview page: counts, the flagged pairs, and the first 20 new rows with the category the rules engine would assign.
6. Commit. Run rules on the new rows. Record the import.
7. **Undo import**: deletes the transactions from that import (unless edited since, in which case warn).

Tests that lock this in: import a 90-day export, then import a fresh 90-day export taken two weeks later. Only the two weeks of new rows land. Import the first file a second time: zero rows land. Import a shorter export that's a strict subset: zero rows land.

### 3.2 Rules engine

Rules are ordered by priority. First match wins. A rule can set category, sub-budget, a clean merchant name, mark as excluded, or mark as transfer. A rule can be scoped to one account and to a date range, which is how "every `TURTUR` merchant on the Apple Card between Sep 1 and Sep 14 goes to the Istanbul trip" becomes one rule instead of forty edits.

Built-in rules that ship enabled:
- Chase card `Type = Payment` → transfer
- Apple Card `Type = Payment` → transfer
- Chase checking `Type in (ACCT_XFER, LOAN_PMT)` and descriptions matching `Payment to Chase card`, `APPLECARD GSBANK PAYMENT`, `SCHWAB BANK TRANSFER` → transfer
- Chase checking `Type = ACH_CREDIT` with `PAYROLL` in the description → income, excluded from spend

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

- `carry_all` (default): overspend last month reduces this month
- `carry_positive_only`: unspent carries forward, overspend is forgiven
- `none`: carry is always 0

Optional `rollover_cap` stops a category building an unbounded pot. Rollover starts from the first month the category has a budget. Computed on the fly, month by month from the anchor; cache in a `month_summary` table only if it gets slow, which it won't for a few years of data.

### 3.4 Transfers

Moving money between your own accounts isn't spending. Rules can mark a transaction as `transfer`, and transfers are excluded from every spend figure. Your Sep 15 `APPLECARD GSBANK PAYMENT -5240.41` on Chase checking and the `ACH DEPOSIT ... -5240.41` on the Apple Card are the same event and both must vanish from spend. Later: auto-detect matching pairs (same amount, opposite sign, within 3 days, different accounts) and offer to link them.

### 3.5 Sub-budgets

A sub-budget is a named pot inside a category with a total amount and its own life, not a month. "Istanbul trip, Travel, $4,000, Sep 1 to Sep 14." "Dog training, Pets, $3,900, open-ended." "Kitchen, Home, $15,000, until done."

- A transaction belongs to at most one sub-budget, and it must be in that sub-budget's category. Assign by rule, by bulk edit, or one at a time.
- The sub-budget page shows total, spent, remaining, and a cumulative spend line from start date to today with the total as a flat line. Closed sub-budgets keep their final numbers.
- A sub-budget's transactions count against the category's monthly budget **and** the sub-budget. The trip's restaurants come out of September's Travel envelope, and they also draw down the trip pot. The category's monthly view marks which rows belong to a sub-budget so you can see both at once.
- Sub-budgets don't roll over. They have a total, and they're done when they're closed.
- Dashboard: all active sub-budgets as progress bars, sorted by percent spent.

## 4. Screens

1. **Login**
2. **This month** (home): total budgeted vs total spent for the month, one big pair of numbers and a bar. Below it, a bar per category: budgeted + carry, spent, remaining. Red if over. Active sub-budgets below that. Click through to transactions. No "left to spend" and no income maths: this app tracks the spending budget, not cash.
3. **Transactions**: filterable table (account, month, category, uncategorised, excluded, search). Inline category dropdown. Add manual transaction (income or expense) button.
   **Bulk edit** is a first-class requirement: checkbox per row, select all in current filter, then one action bar for set category, exclude/include, mark as transfer, add tag, delete, or create a rule from the selection. Filter to "Uncategorised, contains TESCO", select all, set Groceries, tick "make this a rule". Every bulk change writes one audit row per transaction and offers a single undo.
4. **Review queue**: uncategorised and flagged transactions since last visit. This is the page you open after an import.
5. **Import**: pick account, upload, preview, commit. Import history with undo.
6. **Categories & budgets**: grid of categories by group with default budget, this month's override, rollover mode. "Copy last month's budgets" button.
6a. **Sub-budgets**: list of active and closed pots with progress. Create, edit total, close. Detail page with the cumulative line and its transactions.
7. **Rules**: list, edit, reorder, hit counts, test a pattern against existing transactions.
8. **Accounts**: add, archive, pick or build a CSV profile.
9. **Dashboards**:
   - Total budget vs total spend, month over month, last 12 months (paired bars)
   - Spend by category, month over month (stacked bar, toggle to lines)
   - One category over time with its budget line and carry
   - Category share this month (donut)
   - Top merchants this month and last 12 months
   - Sub-budgets: all active pots as progress bars; one pot as a cumulative line
   - Spend by person, where the card reports it (Apple Card `Purchased By`)
   - Year to date vs budget
10. **Settings**: users (invite, reset password), currency, backup now, export all as CSV.

### Phone first

Most use will be from a phone: checking the month at the shop, categorising a few rows on the sofa. Every page is designed at 375px wide first and widened for the laptop, not the other way round.

- **Transactions on a phone** are a list of cards, not a table: merchant and amount on one line, date and category chip below, tap the chip to change category, swipe or long-press to select for bulk edit. The table view is for wide screens only.
- **Category dropdowns** open a bottom sheet with a search box, not a native select with 40 options.
- **Bulk edit action bar** sticks to the bottom of the screen above the thumb.
- **Charts** shrink to one column, legends collapse to tap-to-toggle, and the 12-month charts scroll horizontally rather than squashing.
- **Import** works from the phone's file picker, so a CSV downloaded on the phone can go straight in.
- **Navigation** is a bottom tab bar on phones (This month, Transactions, Review, Dashboards, More) and a sidebar on wide screens.
- Tap targets 44px minimum. No hover-only controls.
- **Home screen install**: a web manifest and icon so it can be added to the iPhone home screen and opens full-screen like an app. No offline mode, the Pi has to be reachable.
- The CI screenshot job renders each page at 375px and 1280px so a layout break is caught before it reaches the Pi.

## 5. Features you didn't list but will want

- **Review queue after import** (above). Without it, uncategorised transactions pile up silently.
- **Transfers** (above). Without it, the $5,240 Apple Card payment looks like the month's biggest expense.
- **Import preview and undo.** The first few imports will go wrong while the CSV profile is being tuned.
- **Split transactions.** One Amazon order, two categories.
- **Category locking.** A manual categorisation must survive rule re-runs.
- **Multiple accounts.** Chase checking, Chase card, Apple Card today. Each has its own CSV format.
- **Notes and tags** on a transaction. "Birthday present for Mum."
- **Audit log.** Who changed what. Useful in a shared household when a transaction moves.
- **Nightly backup.** A cron in the container copies the SQLite file to a `backups/` volume and keeps 30 days. You can point that at a USB stick or a synced folder. The dashboards are worthless if the Pi's SD card dies with the only copy.
- **CSV export** of everything. Your data, your way out.
- **Recurring detection** (later). Flag transactions that show up monthly with the same merchant and near-same amount, so bills are known before they arrive.
- **Annual budgets** (later). Car insurance is once a year. A sub-budget with a 12-month window covers this well enough that it may never need its own feature.
- **Dark mode.** Cheap with CSS variables; do it from the start.

Out of scope on purpose: bank API connections (Plaid costs money and needs a registered app), income and cash-position tracking (you do that elsewhere), savings goals, investment tracking, multi-currency, push notifications.

## 6. Build phases

Each phase ends with something usable and pushed.

**Phase 0: Scaffold** (½ day)
Repo layout, `pyproject.toml`, FastAPI app with a health route, SQLite + Alembic, Dockerfile, compose file, GitHub Actions running ruff/mypy/pytest. `make dev` runs it on the laptop at `http://localhost:8000`.

**Phase 1: Users and accounts** (1 day)
Login, sessions, first-run admin setup, invite second user. Accounts CRUD. Base layout with the bottom tab bar on phones and sidebar on wide screens, dark mode, web manifest for home-screen install. Playwright screenshot job at 375px and 1280px in CI.

**Phase 2: CSV import** (2 days)
The three profiles above, plus the column-picker UI. Parser, normaliser, fingerprinting, three-bucket dedupe, preview, commit, undo. This phase gets the most tests, using anonymised slices of your three real exports as fixtures: re-import produces zero new rows, overlapping exports dedupe correctly, the 22 identical Belbim rows all survive, the Chase checking trailing comma parses, pending → posted gets flagged.

**Phase 3: Transactions and categories** (1½ days)
Categories with groups. Transactions as cards on phones and a table on wide screens, filters, category bottom sheet, exclude, manual add (income and expense), delete, transfers, notes. Bulk edit with select-all-in-filter, the sticky action bar, and undo.

**Phase 4: Rules** (1 day)
Rules CRUD, "create rule from this transaction", apply-to-existing, category locking, review queue page, rules run at import commit.

**Phase 5: Budgets, rollover, sub-budgets** (1½ days)
Default and per-month budgets, copy last month, rollover modes and cap, the "this month" home page with total budget vs spend and per-category bars. Sub-budgets: model, pages, assignment by rule and bulk edit. Rollover and sub-budget maths get table-driven tests.

**Phase 6: Dashboards** (1½ days)
The eight charts above. One SQL query module that returns month × category aggregates; every chart reads from it. Vendored Chart.js.

**Phase 7: Pi deployment** (½ day)
Multi-arch image pushed to GitHub Container Registry. `docker compose up -d` on the Pi with `restart: unless-stopped`. Volume for the DB and backups. Nightly backup cron. Tailscale setup notes. Optional Caddy for HTTPS on a `.local` name.

**Phase 8: Polish** (ongoing)
Splits, recurring detection, transfer pairing, annual budgets, CSV export, search.

Total to a daily-use app: about 10 working days through Phase 7.

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
    budgets/             rollover maths, sub-budget maths, month summaries
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

## 9. Settled

- Accounts: Chase checking (2630), Chase credit card (8393), Apple Card. Profiles built from the Sep 20 2026 exports.
- Currency: USD.
- Rollover default: `carry_all`.
- No "left to spend". Home page is total budget vs total spend.
- Income and cash position are tracked elsewhere. Payroll and transfers are excluded from spend by default rules.
- Bulk edit and sub-budgets are first-class.
- Phone first. Designed at 375px, widened for the laptop. Installable to the home screen.
- Two logins, one each, with an audit trail.
- Sub-budget spend counts against the monthly category budget as well as the sub-budget.
- Chase checking is imported. Default rules hide payroll, mortgage, and transfers so Venmo and Zelle spend is still caught.
- Imports are overlapping running exports. Only unseen rows are added. Existing rows are never touched by an import.

## 10. Still open

Nothing blocking. Phase 0 can start.
