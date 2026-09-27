"""Runs the saved_scores table drop against a real database, both ways.

The model and routes came off in an earlier release
(tests/test_saved_score_unmapped_columns.py guards that half); this is the half
that removes the table. The session database is already at head, so every other
test runs without it -- what is left to pin here is that the migration is the
thing that removed it, that nothing else goes with it, and that a rollback puts
back a table the previous image could have read.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "18af83d5c624"
DROP_REVISION = "0ffde4301ddb"
MIGRATION_DB_NAME = "hymn_drop_saved_scores_migration_test"
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
    """A database one revision short of the drop, holding one song and one entry."""
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
        _seed(engine)
        yield engine
    finally:
        engine.dispose()
        os.environ["DATABASE_URL"] = original_url
        _drop_database(MIGRATION_DB_NAME)


def _seed(engine) -> None:
    file = "'https://b/k.png', 'scores/church-1/k.png'"
    statements = [
        "INSERT INTO churches (id, name, join_code, timezone, created_at) "
        "VALUES ('church-1', '교회', 'code0001', 'Asia/Seoul', now())",
        "INSERT INTO users (id, church_id, email, name, role, created_at) "
        "VALUES ('user-1', 'church-1', 'u@example.com', 'u', 'leader', now())",
        "INSERT INTO songs (id, church_id, title, title_key, file_url, file_uri, "
        f"created_at, updated_at) VALUES ('song-1', 'church-1', '은혜', '은혜', {file}, now(), now())",
        "INSERT INTO saved_scores (id, user_id, song_id, created_at) VALUES ('saved-1', 'user-1', 'song-1', now())",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _table_exists(engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_regclass('public.saved_scores') IS NOT NULL")).scalar_one()


def _shape(engine) -> dict:
    """Columns, constraints and indexes of saved_scores, as Postgres spells them."""
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_name = 'saved_scores' "
                "ORDER BY ordinal_position"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'saved_scores'::regclass ORDER BY conname"
            )
        ).all()
        indexes = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'saved_scores' ORDER BY indexname")
        ).all()
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def test_upgrade_should_drop_saved_scores(migration_db):
    # Arrange
    assert _table_exists(migration_db)

    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)

    # Assert
    assert not _table_exists(migration_db)


def test_upgrade_should_leave_the_songs_and_users_it_pointed_at(migration_db):
    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)

    # Assert — the entry's FKs cascaded from those rows, never to them
    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT id FROM songs")).scalars().all() == ["song-1"]
        assert conn.execute(text("SELECT id FROM users")).scalars().all() == ["user-1"]


def test_downgrade_should_restore_the_table_as_it_was_and_empty(migration_db):
    # Arrange
    before = _shape(migration_db)

    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert — shape only: the rows a drop took do not come back
    assert _shape(migration_db) == before
    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM saved_scores")).scalar_one() == 0
