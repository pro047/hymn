"""Runs the set_items key/memo drop against a real database, both ways.

The mapping came off in an earlier release (tests/test_set_item_unmapped_columns.py
guards that half); this is the half that removes the columns themselves. The
session database is already at head, so every other test runs without them --
what is left to pin here is that the migration is the thing that removed them,
and that a rollback puts back a schema the previous image can read.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "d8a41c6f2b93"
DROP_REVISION = "a9c4e2f7b1d6"
MIGRATION_DB_NAME = "hymn_drop_key_memo_migration_test"
MIGRATION_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB_NAME}"


def _alembic_config() -> Config:
    config = Config(os.path.join(BASE_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
    return config


def _drop_database(name: str) -> None:
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        # A single leftover connection makes DROP DATABASE fail, and the next
        # test would then start against whatever this one left behind.
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin_engine.dispose()


@pytest.fixture()
def migration_db():
    """An empty database one revision short of the drop."""
    _drop_database(MIGRATION_DB_NAME)
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB_NAME}"'))
    admin_engine.dispose()

    # alembic/env.py reads DATABASE_URL when it runs, not when it is imported,
    # so pointing it at this database is enough to keep the session's untouched.
    original_url = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = MIGRATION_DB_URL
    engine = create_engine(MIGRATION_DB_URL, future=True)
    try:
        command.upgrade(_alembic_config(), PREVIOUS_REVISION)
        yield engine
    finally:
        engine.dispose()
        os.environ["DATABASE_URL"] = original_url
        _drop_database(MIGRATION_DB_NAME)


def _set_item_columns(engine) -> dict[str, tuple[str, int | None, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_name = 'set_items'"
            )
        ).all()
    return {name: (data_type, length, nullable) for name, data_type, length, nullable in rows}


def test_upgrade_should_drop_key_and_memo_from_set_items(migration_db):
    assert {"key", "memo"} <= _set_item_columns(migration_db).keys()

    command.upgrade(_alembic_config(), DROP_REVISION)

    remaining = _set_item_columns(migration_db)
    assert "key" not in remaining
    assert "memo" not in remaining
    # Only those two: the columns the app still maps must survive the drop.
    assert {"id", "week_id", "week_date", "order_no", "score_id", "starts_new_page"} <= remaining.keys()


def test_downgrade_should_restore_the_columns_as_they_were(migration_db):
    before = _set_item_columns(migration_db)

    command.upgrade(_alembic_config(), DROP_REVISION)
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    after = _set_item_columns(migration_db)
    assert after["key"] == before["key"]
    assert after["memo"] == before["memo"]
