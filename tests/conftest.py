import os
from pathlib import Path

import pytest

os.environ["BT_SECRET_KEY"] = "test-secret"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    """A TestClient on a fresh temp database, migrated and seeded."""
    from app.config import settings

    monkeypatch.setattr(settings, "database_path", tmp_path / "t.db")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")

    import sqlalchemy as sa

    import app.db as dbmod

    engine = sa.create_engine(settings.database_url, connect_args={"check_same_thread": False})
    sa.event.listen(engine, "connect", dbmod._sqlite_pragmas)
    monkeypatch.setattr(dbmod, "engine", engine)
    dbmod.SessionLocal.configure(bind=engine)

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db(client):
    from app.db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def logged_in(client):
    r = client.post(
        "/setup",
        data={"display_name": "Nikita", "email": "n@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return client
