# Household Budget

A self-hosted spending budget for two people. Import bank CSVs, sort transactions into categories, set monthly budgets that roll over, track one-off pots like a trip, and see where the money went. Runs on a laptop today and a Raspberry Pi later. Built for the phone first.

The design and decisions are in [PLAN.md](PLAN.md).

## Run it on your laptop

You need Docker, or Python 3.12+ with [uv](https://docs.astral.sh/uv/).

With Docker:

```
cp .env.example .env            # set BT_SECRET_KEY to something long and random
docker compose up -d
open http://localhost:8000
```

Without Docker:

```
cp .env.example .env
uv sync
make dev                        # http://localhost:8000
```

The first visit asks you to create the admin user. Then:

1. **Accounts**: add one per card or bank account and pick its CSV profile (Chase credit card, Chase checking, Apple Card are built in).
2. **Import**: upload an export. The preview shows what's new, what was already imported, and anything that needs a look. Nothing is saved until you confirm.
3. **Review**: uncategorised spending grouped by merchant. Pick a category once per group. Leave "make a rule" on and the next import sorts itself.
4. **Budgets**: a monthly amount per category, with an optional override for a single month.
5. **Settings**: invite the second person. They get a link to set their password.

Data lives in `./data/budget.db` (SQLite). Back it up by copying that file, or use the button in Settings. Everything exports as CSV from Settings.

## Run it on a Raspberry Pi

Any Pi 4 or 5 running 64-bit Raspberry Pi OS. The image builds for arm64.

```
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # then log out and back in
git clone <this repo> budget && cd budget
cp .env.example .env               # set BT_SECRET_KEY
docker compose up -d --build
```

The first build on a Pi takes a few minutes. After that, `docker compose up -d` restarts it on boot (`restart: unless-stopped`).

From any device on your home network: `http://<pi-ip>:8000`. Give the Pi a fixed IP in your router so the address doesn't change, or use `http://raspberrypi.local:8000`.

### Add to the phone's home screen

Open the address in Safari (iPhone) or Chrome (Android), then "Add to Home Screen". It opens full-screen like an app.

### Reaching it away from home

Don't open a port on your router. Install [Tailscale](https://tailscale.com) on the Pi and on your phones. The Pi gets a stable address (and a name like `raspberrypi`) that works from anywhere, only for devices you've signed in. Same URL, same app.

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

### Backups

The `backup` service in `docker-compose.yml` copies the database into `./data/backups/` every night and keeps 30 days. SD cards fail. Point that folder somewhere else too: a USB stick mounted at `/mnt/usb` and a bind mount in the compose file, or a folder synced to a cloud drive.

To restore: stop the app, copy a backup over `data/budget.db`, start it again.

```
docker compose stop budget
cp data/backups/budget-20261001.db data/budget.db
docker compose start budget
```

### Updating

```
git pull
docker compose up -d --build
```

Database migrations run automatically on start.

## Configuration

All settings are environment variables with a `BT_` prefix, read from `.env`:

| Variable | Default | What |
|---|---|---|
| `BT_SECRET_KEY` | (required in compose) | Signs the login cookie. Long and random. Changing it logs everyone out. |
| `BT_DATABASE_PATH` | `data/budget.db` | SQLite file. `/data/budget.db` inside the container. |
| `BT_UPLOAD_DIR` | `data/uploads` | Where an uploaded CSV waits between preview and confirm. |
| `BT_PORT` | `8000` | Host port in compose. |
| `BT_CURRENCY_SYMBOL` | `$` | Display only. |
| `BT_SESSION_DAYS` | `30` | How long a login lasts. |

## How the import avoids duplicates

Export a running list from the bank as often as you like. Each row gets a fingerprint from the account, transaction date, post date, amount, cleaned description, running balance if the bank gives one, and a counter for identical rows on the same day. A row whose fingerprint already exists is skipped. A unique index in the database enforces it. Rows already imported are never changed by an import, so your categories and notes stay put.

A row with the same amount within three days of an existing one but a different description is flagged on the preview. That's usually a pending charge that posted under a new name. Skip is the default; keep it if it's really a separate purchase.

## Adding a bank

Import → CSV profiles → New profile. Upload a sample export, pick which column is the date, description, amount (or debit and credit), and the optional extras. Set whether positive numbers mean purchases (like Apple Card) or money in (like a checking account). Then set the profile on the account.

## Development

```
make dev          # run with reload
make test         # pytest
make lint         # ruff
make typecheck    # mypy
make screenshots  # every page at 375px and 1280px, into tests/screenshots/
```

Layout: `app/importer` (parse, fingerprint, dedupe), `app/rules` (matcher), `app/budgets` (rollover and sub-budget maths), `app/reports` (dashboard aggregates), `app/routers` (one per screen), `app/templates` (Jinja2 + HTMX), `app/static` (CSS, vendored HTMX and Chart.js). Tests live in `tests/` with synthetic CSV fixtures under `tests/fixtures/csv/`.

CI runs lint, types, tests, screenshots and a multi-arch Docker build on every push.
