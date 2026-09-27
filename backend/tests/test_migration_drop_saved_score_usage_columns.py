"""Runs the saved_scores usage-column drop against a real database, both ways.

The mapping came off in an earlier release (tests/test_saved_score_unmapped_columns.py
guards that half); this is the half that removes the columns themselves. The
session database is already at head, so every other test runs without them --
what is left to pin here is that the migration is the thing that removed them,
that the entries survive it, and that a rollback puts back a schema the
previous image can read.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "b7e3d1f9a2c4"
DROP_REVISION = "18af83d5c624"
MIGRATION_DB_NAME = "hymn_drop_saved_usage_columns_migration_test"
MIGRATION_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB_NAME}"

DROPPED_COLUMNS = {"score_id", "use_count", "last_used_at"}
USAGE_INDEX = "ix_saved_scores_user_use_last_used"
SCORE_FK = "saved_scores_score_id_fkey"


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
    """A database one revision short of the drop, holding one saved entry."""
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


def _saved_score_columns(engine) -> dict[str, tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = 'saved_scores'"
            )
        ).all()
    return {name: tuple(rest) for name, *rest in rows}


def _index_exists(engine) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT count(*) FROM pg_indexes WHERE indexname = :name"), {"name": USAGE_INDEX}
            ).scalar_one()
            == 1
        )


def _score_fk(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'saved_scores'::regclass AND conname = :name"
            ),
            {"name": SCORE_FK},
        ).scalar_one_or_none()


def test_upgrade_should_drop_the_usage_columns_from_saved_scores(migration_db):
    # Arrange
    assert DROPPED_COLUMNS <= _saved_score_columns(migration_db).keys()

    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)

    # Assert
    remaining = _saved_score_columns(migration_db)
    assert remaining.keys().isdisjoint(DROPPED_COLUMNS)
    # Only those three: the columns the app still maps must survive the drop.
    assert remaining.keys() == {"id", "user_id", "song_id", "created_at"}
    assert not _index_exists(migration_db)
    assert _score_fk(migration_db) is None


def test_upgrade_should_keep_the_saved_entries(migration_db):
    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)

    # Assert
    with migration_db.connect() as conn:
        rows = conn.execute(text("SELECT id, user_id, song_id FROM saved_scores")).all()
    assert rows == [("saved-1", "user-1", "song-1")]


def test_downgrade_should_restore_the_columns_as_they_were(migration_db):
    # Arrange
    before = _saved_score_columns(migration_db)
    fk_before = _score_fk(migration_db)

    # Act
    command.upgrade(_alembic_config(), DROP_REVISION)
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert
    after = _saved_score_columns(migration_db)
    for column in DROPPED_COLUMNS:
        assert after[column] == before[column]
    assert _index_exists(migration_db)
    assert _score_fk(migration_db) == fk_before
    with migration_db.connect() as conn:
        rows = conn.execute(text("SELECT id, score_id, use_count, last_used_at FROM saved_scores")).all()
    # Shape only: the values a drop took do not come back.
    assert rows == [("saved-1", None, 0, None)]
