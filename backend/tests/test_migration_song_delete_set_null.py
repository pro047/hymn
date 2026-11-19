"""Runs the song_id SET NULL migration against a real database, both ways.

Deleting a song from the library takes the song row only: every Sunday it was
filed on keeps its own copy of the title and file, so the foreign key from
scores has to let go (SET NULL) rather than take the week with it (CASCADE).
What is pinned here is the schema the migration leaves, that it moves no data,
and that a rollback refuses -- rather than deletes -- once a week has lost its
song.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "0ffde4301ddb"
SET_NULL_REVISION = "e4b2c8d6f1a3"
MIGRATION_DB_NAME = "hymn_song_delete_set_null_migration_test"
MIGRATION_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB_NAME}"
FK_NAME = "fk_scores_song_id_songs"


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
    """A database one revision short of SET NULL: two songs, each on one Sunday."""
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
    statements = [
        "INSERT INTO churches (id, name, join_code, timezone, created_at) "
        "VALUES ('church-1', '교회', 'code0001', 'Asia/Seoul', now())",
        "INSERT INTO users (id, church_id, email, name, role, created_at) "
        "VALUES ('user-1', 'church-1', 'u@example.com', 'u', 'leader', now())",
        "INSERT INTO songs (id, church_id, title, title_key, file_url, file_uri, created_at, updated_at) VALUES "
        "('song-1', 'church-1', '은혜', '은혜', 'https://b/1.png', 'scores/church-1/1.png', now(), now()), "
        "('song-2', 'church-1', '평안', '평안', 'https://b/2.png', 'scores/church-1/2.png', now(), now())",
        "INSERT INTO scores (id, church_id, song_id, title, week_of, file_url, file_uri, "
        "status, created_at, updated_at) VALUES "
        "('usage-1', 'church-1', 'song-1', '은혜', '2026-09-06', "
        "'https://b/1.png', 'scores/church-1/1.png', 'draft', now(), now()), "
        "('usage-2', 'church-1', 'song-2', '평안', '2026-09-13', "
        "'https://b/2.png', 'scores/church-1/2.png', 'draft', now(), now())",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _rows(engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, song_id, title, file_uri, week_of FROM scores ORDER BY id")
        ).all()


def _is_nullable(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'scores' AND column_name = 'song_id'"
            )
        ).scalar_one()


def _fk_definition(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'scores'::regclass AND conname = :name"
            ),
            {"name": FK_NAME},
        ).scalar_one()


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _shape(engine) -> dict:
    """Columns, constraints and indexes of scores, as Postgres spells them."""
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_name = 'scores' "
                "ORDER BY ordinal_position"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'scores'::regclass ORDER BY conname"
            )
        ).all()
        indexes = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'scores' ORDER BY indexname")
        ).all()
    return {"columns": columns, "constraints": constraints, "indexes": indexes}


def _delete_song(engine, song_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM songs WHERE id = :id"), {"id": song_id})


# AC-1
def test_upgrade_should_make_song_id_nullable_with_set_null_and_keep_every_row(migration_db):
    # Arrange
    before = _rows(migration_db)
    assert _is_nullable(migration_db) == "NO"
    assert "ON DELETE CASCADE" in _fk_definition(migration_db)

    # Act
    command.upgrade(_alembic_config(), SET_NULL_REVISION)

    # Assert
    assert _is_nullable(migration_db) == "YES"
    definition = _fk_definition(migration_db)
    assert "ON DELETE SET NULL" in definition
    assert "REFERENCES songs(id)" in definition
    assert _rows(migration_db) == before
    assert [row.song_id for row in _rows(migration_db)] == ["song-1", "song-2"]
    assert _version(migration_db) == SET_NULL_REVISION


# AC-1: the index on song_id the lookups use survives the FK being recreated.
def test_upgrade_should_keep_the_song_id_index(migration_db):
    # Arrange
    before = _shape(migration_db)["indexes"]

    # Act
    command.upgrade(_alembic_config(), SET_NULL_REVISION)

    # Assert
    assert _shape(migration_db)["indexes"] == before
    assert "ix_scores_song_id" in [name for name, _ in before]


# AC-2
def test_deleting_a_song_after_upgrade_should_empty_song_id_on_its_weeks_and_keep_them(migration_db):
    # Arrange — song-1 on a second Sunday too, so "its weeks" means more than one.
    with migration_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scores (id, church_id, song_id, title, week_of, file_url, file_uri, "
                "status, created_at, updated_at) VALUES ('usage-3', 'church-1', 'song-1', '은혜', "
                "'2026-09-20', 'https://b/1.png', 'scores/church-1/1.png', 'draft', now(), now())"
            )
        )
    command.upgrade(_alembic_config(), SET_NULL_REVISION)

    # Act
    _delete_song(migration_db, "song-1")

    # Assert
    assert _rows(migration_db) == [
        ("usage-1", None, "은혜", "scores/church-1/1.png", date(2026, 9, 6)),
        ("usage-2", "song-2", "평안", "scores/church-1/2.png", date(2026, 9, 13)),
        ("usage-3", None, "은혜", "scores/church-1/1.png", date(2026, 9, 20)),
    ]
    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT id FROM songs ORDER BY id")).scalars().all() == ["song-2"]


# AC-3
def test_downgrade_without_emptied_rows_should_restore_not_null_cascade_and_the_shape(migration_db):
    # Arrange
    before_shape = _shape(migration_db)
    before_rows = _rows(migration_db)
    command.upgrade(_alembic_config(), SET_NULL_REVISION)

    # Act
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert
    assert _is_nullable(migration_db) == "NO"
    assert "ON DELETE CASCADE" in _fk_definition(migration_db)
    assert _shape(migration_db) == before_shape
    assert _rows(migration_db) == before_rows
    assert _version(migration_db) == PREVIOUS_REVISION


# AC-3: a rollback can be rolled forward again.
def test_upgrade_after_downgrade_should_set_null_again(migration_db):
    # Arrange
    command.upgrade(_alembic_config(), SET_NULL_REVISION)
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Act
    command.upgrade(_alembic_config(), SET_NULL_REVISION)

    # Assert
    assert _is_nullable(migration_db) == "YES"
    assert "ON DELETE SET NULL" in _fk_definition(migration_db)
    assert [row.song_id for row in _rows(migration_db)] == ["song-1", "song-2"]


# AC-4
def test_downgrade_with_an_emptied_row_should_refuse_and_change_nothing(migration_db):
    # Arrange
    command.upgrade(_alembic_config(), SET_NULL_REVISION)
    _delete_song(migration_db, "song-1")
    shape_before = _shape(migration_db)

    # Act
    with pytest.raises(RuntimeError):
        command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert — the week that lost its song is still there, and so is the schema.
    with migration_db.connect() as conn:
        orphan = conn.execute(text("SELECT song_id, title FROM scores WHERE id = 'usage-1'")).one()
    assert tuple(orphan) == (None, "은혜")
    assert [row.id for row in _rows(migration_db)] == ["usage-1", "usage-2"]
    assert _is_nullable(migration_db) == "YES"
    assert "ON DELETE SET NULL" in _fk_definition(migration_db)
    assert _shape(migration_db) == shape_before
    assert _version(migration_db) == SET_NULL_REVISION
