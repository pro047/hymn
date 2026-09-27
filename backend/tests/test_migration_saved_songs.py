"""Runs the song-centric saved_scores migration against a real database, both ways.

The library held one weekly usage per entry, so deleting that week's usage took
the entry with it (ON DELETE CASCADE) even while the song was still sung on
other Sundays. After the migration an entry belongs to the song; the usage it
was first saved from may go without taking it along.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "a9c4e2f7b1d6"
SONG_CENTRIC_REVISION = "b7e3d1f9a2c4"
MIGRATION_DB_NAME = "hymn_saved_songs_migration_test"
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
    """A database one revision short of the song-centric library."""
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


def _seed(engine) -> None:
    """One church, one user, one song used on two Sundays, the first saved."""
    file = "'https://b/k.png', 'scores/church-1/k.png'"
    statements = [
        "INSERT INTO churches (id, name, join_code, timezone, created_at) "
        "VALUES ('church-1', '교회', 'code0001', 'Asia/Seoul', now())",
        "INSERT INTO users (id, church_id, email, name, role, created_at) "
        "VALUES ('user-1', 'church-1', 'u@example.com', 'u', 'leader', now())",
        "INSERT INTO songs (id, church_id, title, title_key, file_url, file_uri, "
        f"created_at, updated_at) VALUES ('song-1', 'church-1', '은혜', '은혜', {file}, now(), now())",
        "INSERT INTO scores (id, church_id, song_id, title, week_of, file_url, file_uri, "
        "status, created_at, updated_at) VALUES "
        f"('usage-1', 'church-1', 'song-1', '은혜', '2026-09-06', {file}, 'draft', now(), now()), "
        f"('usage-2', 'church-1', 'song-1', '은혜', '2026-09-13', {file}, 'draft', now(), now())",
        "INSERT INTO saved_scores (id, user_id, score_id, use_count, created_at) "
        "VALUES ('saved-1', 'user-1', 'usage-1', 3, now())",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _saved_rows(engine) -> list[tuple]:
    with engine.connect() as conn:
        return conn.execute(text("SELECT id, song_id, score_id FROM saved_scores ORDER BY id")).all()


def test_upgrade_should_point_each_saved_entry_at_its_song(migration_db):
    # Arrange
    _seed(migration_db)

    # Act
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)

    # Assert
    assert _saved_rows(migration_db) == [("saved-1", "song-1", "usage-1")]


def test_deleting_the_usage_it_was_saved_from_should_keep_the_entry(migration_db):
    # Arrange
    _seed(migration_db)
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)

    # Act — the Sunday it was first saved from is taken off
    with migration_db.begin() as conn:
        conn.execute(text("DELETE FROM set_items WHERE score_id = 'usage-1'"))
        conn.execute(text("DELETE FROM scores WHERE id = 'usage-1'"))

    # Assert — still saved, still the song, the usage link cleared
    assert _saved_rows(migration_db) == [("saved-1", "song-1", None)]


def test_a_user_should_save_a_song_only_once(migration_db):
    # Arrange
    _seed(migration_db)
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)

    # Act / Assert — the other Sunday of the same song is the same entry
    with pytest.raises(Exception, match="uq_saved_scores_user_song"):
        with migration_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO saved_scores (id, user_id, song_id, score_id, created_at) "
                    "VALUES ('saved-2', 'user-1', 'song-1', 'usage-2', now())"
                )
            )


def test_an_entry_without_a_song_should_be_refused(migration_db):
    # Arrange
    _seed(migration_db)
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)

    # Act / Assert — what an older image would send on a rollback
    with pytest.raises(Exception, match="song_id"):
        with migration_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO saved_scores (id, user_id, score_id, use_count, created_at) "
                    "VALUES ('saved-2', 'user-1', 'usage-2', 0, now())"
                )
            )


def test_downgrade_should_restore_the_usage_centric_table(migration_db):
    # Arrange
    _seed(migration_db)
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)

    # Act
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert — the entry is back on its usage and the cascade is back too
    with migration_db.connect() as conn:
        columns = conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'saved_scores'")
        ).scalars().all()
        fk = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'saved_scores'::regclass AND conname = 'saved_scores_score_id_fkey'"
            )
        ).scalar_one()
        row = conn.execute(text("SELECT id, score_id FROM saved_scores")).all()
    assert "song_id" not in columns
    assert "ON DELETE CASCADE" in fk
    assert row == [("saved-1", "usage-1")]


def test_downgrade_should_drop_entries_that_no_longer_have_a_usage(migration_db):
    # Arrange — an entry whose usage was deleted after the upgrade
    _seed(migration_db)
    command.upgrade(_alembic_config(), SONG_CENTRIC_REVISION)
    with migration_db.begin() as conn:
        conn.execute(text("DELETE FROM set_items WHERE score_id = 'usage-1'"))
        conn.execute(text("DELETE FROM scores WHERE id = 'usage-1'"))

    # Act — the old shape has no place for it: score_id was NOT NULL
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)

    # Assert
    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM saved_scores")).scalar_one() == 0
