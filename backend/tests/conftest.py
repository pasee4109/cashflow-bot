"""Pytest fixtures — run the app against a throwaway SQLite DB in Demo mode."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ["ALLOW_DEV_LOGIN"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    init_db()


@pytest.fixture
def client():
    c = TestClient(app)
    c.post("/api/auth/dev-login", params={"email": "test@example.com"})
    return c


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
