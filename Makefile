.PHONY: dev test lint fmt typecheck screenshots

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $${BT_PORT:-8000}

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy app

screenshots:
	uv run python scripts/screenshots.py
