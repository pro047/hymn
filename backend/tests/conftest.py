import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_DIR, "src"))

TEST_DB_NAME = os.getenv("TEST_DB_NAME", "hymn_test")
ADMIN_DB_URL = os.getenv(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg2://appuser:devpass@localhost:55432/postgres",
)
TEST_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"

# Must be set before importing app modules (read at import time).
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("AUTH_SECRET", "test-secret")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app
from app.rate_limit import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Gives every test an empty rate-limit window.

    The limiter keys on the caller's address and TestClient always presents the
    same one, so counters would otherwise accumulate across the whole session and
    fail whichever test happened to run once a limit was reached.
    """
    limiter.reset()
    yield


@pytest.fixture(scope="session")
def engine():
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()

    alembic_cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(TEST_DB_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """A client whose requests look like they came through the local nginx.

    `client=` sets the socket peer. Loopback is what the rate limiter requires
    before it will honour X-Real-IP, so this makes tests exercise the same path
    production takes; TestClient's default peer ("testclient") is not an address
    at all and would be treated as a direct, unproxied connection.
    """
    app.dependency_overrides[get_session] = lambda: db_session
    with TestClient(app, client=("127.0.0.1", 51000)) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_session, None)
