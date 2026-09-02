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
# Production defaults this off (see routes/auth.py). The suite turns it on so the
# reset routes are mounted; that they are *absent* when it is off is covered by
# test_auth_password_reset.py, which reads the flag in a subprocess.
os.environ["PASSWORD_RESET_ENABLED"] = "true"
# With the flag on, require_deliverable_transport refuses to let the app import
# unless both of these are named explicitly — no defaults, so a deployment
# cannot disarm the guard by leaving them out. The suite has to say the same.
os.environ["APP_ENV"] = "test"
os.environ["EMAIL_SENDER"] = "console"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import login_guard
from app.db import get_session
from app.main import app
from app.rate_limit import limiter
from app.services import token_sweep
from app.services.auth import _decoy_password_hash, pwd_context

# Captured before anything lowers it, so a test can put the real cost back.
# to_dict() does not spell the rounds out — they are the scheme default — which
# is exactly why the original config is kept rather than a number.
PRODUCTION_CRYPT_CONFIG = pwd_context.to_dict()
TEST_BCRYPT_ROUNDS = 4


def _set_bcrypt_cost(rounds: int | None) -> None:
    """Lowers the bcrypt cost factor, or restores the production one."""
    if rounds is None:
        pwd_context.load(PRODUCTION_CRYPT_CONFIG)
    else:
        pwd_context.update(bcrypt__rounds=rounds)
    # A bcrypt hash carries its own cost factor, and the decoy is lru_cached:
    # without this the cached one keeps whatever rounds it was built at and
    # verifying against it costs that, not whatever was just set here.
    _decoy_password_hash.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def cheap_bcrypt():
    """bcrypt is deliberately slow and the auth tests live in it — one round per
    login, ten per lockout test, which was most of the suite's wall clock.

    Only the cost factor changes: the hash format, the verify path and every
    result stay identical. Tests that measure durations opt back out with the
    production_bcrypt_cost fixture below.
    """
    _set_bcrypt_cost(TEST_BCRYPT_ROUNDS)
    yield
    _set_bcrypt_cost(None)


@pytest.fixture()
def production_bcrypt_cost():
    """Restores the real cost for tests that compare how long two paths take.

    At four rounds a hash is under a millisecond, which the HTTP round trip and
    the queries around it would swamp — the ratio being asserted would stop
    measuring bcrypt and start measuring noise.
    """
    _set_bcrypt_cost(None)
    yield
    _set_bcrypt_cost(TEST_BCRYPT_ROUNDS)


@pytest.fixture(autouse=True)
def reset_throttles():
    """Gives every test empty rate-limit, lockout and sweep-throttle state.

    All three key on something the whole session shares — the limiter on the
    caller's address, which TestClient always presents the same, the login
    guard on the email, which the auth tests reuse across files, and the sweep
    throttle on nothing at all (it is process-global). Without this the state
    accumulates and whichever test runs after a limit is reached, or after the
    sweep throttle is already claimed, is the one that fails.
    """
    limiter.reset()
    login_guard.reset()
    token_sweep.reset()
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
