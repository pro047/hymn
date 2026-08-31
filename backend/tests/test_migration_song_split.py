"""Runs the song-split migration against a real database, both ways.

Follows test_migration_join_code.py: each test gets its own database, upgraded
to the revision just before the split, seeded with rows shaped like the 150 in
production (spacing variants, one library row with week_of NULL, two churches
sharing a title), and then stepped over the migration.

The properties that matter:
- Grouping is (church, normalized title): a spacing variant must land in the
  same song, the same title in another church must not.
- The representative is the most recent *used* row (week_of DESC NULLS LAST,
  created_at DESC) — its file becomes the song's file. A library row with the
  newest created_at must lose to any row that has a week.
- Row counts are asserted against what was seeded, and the downgrade is
  lossless because the snapshot columns never move.
"""

import importlib.util
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.services.song import normalize_title
from conftest import ADMIN_DB_URL, BASE_DIR

PREVIOUS_REVISION = "e1b6d4c39a75"
MIGRATION_DB_NAME = "hymn_song_split_migration_test"
MIGRATION_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB_NAME}"

MIGRATION_PATH = os.path.join(
    BASE_DIR, "alembic", "versions", "d2a7e5f1c3b9_split_songs_from_scores.py"
)


def _alembic_config() -> Config:
    config = Config(os.path.join(BASE_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BASE_DIR, "alembic"))
    return config


def _drop_database(name: str) -> None:
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
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
    """An empty database one revision short of the song split."""
    _drop_database(MIGRATION_DB_NAME)
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB_NAME}"'))
    admin_engine.dispose()

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


def _upgrade() -> None:
    command.upgrade(_alembic_config(), "head")


def _downgrade() -> None:
    # By name, not "-1": a revision landing on top of this one must not change
    # what this test steps back over.
    command.downgrade(_alembic_config(), PREVIOUS_REVISION)


def _seed_church(engine, church_id: str, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO churches (id, name, join_code, timezone, created_at) "
                "VALUES (:id, :name, :code, 'Asia/Seoul', now())"
            ),
            {"id": church_id, "name": name, "code": church_id[-8:]},
        )


def _seed_score(
    engine, *, score_id, church_id, title, week_of, file_name, created_at
) -> None:
    key = f"scores/{church_id}/{file_name}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO scores (id, church_id, uploader_id, title, week_of, "
                "file_url, file_uri, status, created_at, updated_at) "
                "VALUES (:id, :church_id, NULL, :title, :week_of, "
                ":file_url, :file_uri, 'draft', :created_at, :created_at)"
            ),
            {
                "id": score_id,
                "church_id": church_id,
                "title": title,
                "week_of": week_of,
                "file_url": f"https://bucket.example.com/{key}",
                "file_uri": key,
                "created_at": created_at,
            },
        )


# Production-shaped fixture. Group A (church-1) is the interesting one:
#   a-old   week 2026-01-04  file a-old.png    (oldest use)
#   a-mid   week 2026-01-11  file a-old.png
#   a-new   week 2026-01-18  file a-new.png    <- latest week: representative
#   a-space week 2025-12-28  title " A" (spacing variant, must join the group)
#   a-lib   week NULL        file a-lib.png, *newest* created_at
#           <- NULLS LAST must beat created_at DESC, or the library copy
#              becomes the canonical file
SEED = [
    dict(score_id="a-old", church_id="church-1", title="A", week_of="2026-01-04",
         file_name="a-old.png", created_at="2026-01-01 10:00:00"),
    dict(score_id="a-mid", church_id="church-1", title="A", week_of="2026-01-11",
         file_name="a-old.png", created_at="2026-01-08 10:00:00"),
    dict(score_id="a-new", church_id="church-1", title="A", week_of="2026-01-18",
         file_name="a-new.png", created_at="2026-01-15 10:00:00"),
    dict(score_id="a-space", church_id="church-1", title=" A", week_of="2025-12-28",
         file_name="a-space.png", created_at="2025-12-25 10:00:00"),
    dict(score_id="a-lib", church_id="church-1", title="A", week_of=None,
         file_name="a-lib.png", created_at="2026-02-01 10:00:00"),
    dict(score_id="b-1", church_id="church-1", title="B", week_of="2026-01-04",
         file_name="b1.png", created_at="2026-01-02 10:00:00"),
    dict(score_id="c-1", church_id="church-1", title="C", week_of=None,
         file_name="c.png", created_at="2026-01-03 10:00:00"),
    dict(score_id="b-2", church_id="church-2", title="B", week_of="2026-01-04",
         file_name="b2.png", created_at="2026-01-02 10:00:00"),
]


def _seed_all(engine) -> None:
    _seed_church(engine, "church-1", "가교회")
    _seed_church(engine, "church-2", "나교회")
    for row in SEED:
        _seed_score(engine, **row)


def _song_of(engine, score_id: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT song_id FROM scores WHERE id = :id"), {"id": score_id}
        ).scalar()


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


# --- case 10: upgrade groups, picks the right representative -----------------


def test_upgrade_should_group_usages_into_songs(migration_db):
    _seed_all(migration_db)

    _upgrade()

    # 4 songs: church-1 {A, B, C}, church-2 {B} — the spacing variant merged,
    # the cross-church B did not.
    assert _scalar(migration_db, "SELECT count(*) FROM songs") == 4
    assert _song_of(migration_db, "a-space") == _song_of(migration_db, "a-new")
    assert _song_of(migration_db, "b-1") != _song_of(migration_db, "b-2")
    # Every seeded row kept, every one attached.
    assert _scalar(migration_db, "SELECT count(*) FROM scores") == len(SEED)
    assert _scalar(migration_db, "SELECT count(*) FROM scores WHERE song_id IS NULL") == 0


def test_upgrade_should_take_the_file_of_the_most_recent_week(migration_db):
    """The canonical file is the one the church used last (D6) — and a library
    row with the newest created_at must not win over a row that has a week."""
    _seed_all(migration_db)

    _upgrade()

    with migration_db.connect() as conn:
        song = conn.execute(
            text(
                "SELECT title, file_uri, created_at FROM songs "
                "WHERE church_id = 'church-1' AND title_key = 'a'"
            )
        ).mappings().one()
    assert song["file_uri"] == "scores/church-1/a-new.png"
    # Display title comes from the representative, stripped.
    assert song["title"] == "A"
    # The song's created_at is the group's first appearance, not the latest.
    assert str(song["created_at"]).startswith("2025-12-25")


# --- case 11: downgrade is lossless ------------------------------------------


def test_downgrade_should_remove_the_split_and_keep_every_snapshot(migration_db):
    _seed_all(migration_db)
    _upgrade()

    _downgrade()

    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('songs')")).scalar() is None
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'scores'"
                )
            )
        }
        assert "song_id" not in columns
        # The snapshots never moved, so the old code gets back exactly what it
        # had — including the spacing variant's own title and file.
        row = conn.execute(
            text("SELECT title, file_uri FROM scores WHERE id = 'a-space'")
        ).one()
    assert row[0] == " A"
    assert row[1] == "scores/church-1/a-space.png"
    assert _scalar(migration_db, "SELECT count(*) FROM scores") == len(SEED)


# --- round trip: up -> down -> up --------------------------------------------


def test_the_round_trip_should_rebuild_the_same_grouping(migration_db):
    _seed_all(migration_db)
    _upgrade()
    _downgrade()

    _upgrade()

    assert _scalar(migration_db, "SELECT count(*) FROM songs") == 4
    assert _scalar(migration_db, "SELECT count(*) FROM scores WHERE song_id IS NULL") == 0
    assert _song_of(migration_db, "a-space") == _song_of(migration_db, "a-new")
    with migration_db.connect() as conn:
        file_uri = conn.execute(
            text(
                "SELECT file_uri FROM songs "
                "WHERE church_id = 'church-1' AND title_key = 'a'"
            )
        ).scalar()
    assert file_uri == "scores/church-1/a-new.png"


# --- case 12: empty database -------------------------------------------------


def test_up_and_down_should_pass_on_an_empty_scores_table(migration_db):
    _upgrade()
    assert _scalar(migration_db, "SELECT count(*) FROM songs") == 0

    _downgrade()
    with migration_db.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('songs')")).scalar() is None

    _upgrade()
    assert _scalar(migration_db, "SELECT count(*) FROM songs") == 0


# --- case 14: the two normalization copies must agree ------------------------


def _migration_normalize():
    """The migration keeps its own copy of the rule on purpose (it must stay
    pinned to what it ran with); this loads that copy so the two can be
    compared. Loaded from the file, not alembic's importer — a second module
    object is exactly what the comparison needs."""
    spec = importlib.util.spec_from_file_location("song_split_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None, MIGRATION_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._normalize_title


def test_both_normalization_copies_should_agree_on_every_variant():
    migration_norm = _migration_normalize()
    fullwidth_space = chr(0x3000)  # renders like a space; chr() keeps it real
    nbsp = chr(0x00A0)
    variants = [
        "참 아름다워라",
        " 참 아름다워라 ",
        "참아름다워라",
        "참  아름다워라",
        "참" + fullwidth_space + "아름다워라",
        "참" + nbsp + "아름다워라",
        "Amazing Grace",
        "amazing grace",
        "",
    ]

    for title in variants:
        assert migration_norm(title) == normalize_title(title), repr(title)


def test_the_rule_itself_should_be_pinned_not_just_the_parity():
    """Parity alone passes when both copies are identity functions; the value
    is what actually decides which rows merge."""
    assert normalize_title(" Amazing  Grace ") == "amazinggrace"
    assert normalize_title("참 아름다워라") == "참아름다워라"
    assert normalize_title("참" + chr(0x3000) + "아름다워라") == "참아름다워라"
