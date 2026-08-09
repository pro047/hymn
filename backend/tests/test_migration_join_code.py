"""Runs the invite-code migration against a real database, both ways.

The round trip is the point. The dev-stack check this replaces asserted that
every church held a code and that no two matched — both of which stay true when
a rollback and roll-forward silently reissues the lot, which is exactly what it
was doing. An invariant that survives the change it was meant to catch is not a
check, and this file exists because that one was not.

Each test gets a database of its own rather than the session's: downgrading the
shared one would take the schema out from under every other test in the run.
"""

import os
import secrets

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import ADMIN_DB_URL, BASE_DIR

# The revision this migration builds on; the fixture stops here so a test can
# seed rows that predate the invite code and then step over it.
PREVIOUS_REVISION = "b3e5a7c9d1f2"
MIGRATION_DB_NAME = "hymn_migration_test"
MIGRATION_DB_URL = ADMIN_DB_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB_NAME}"

ALPHABET = set("abcdefghijkmnpqrstuvwxyz23456789")


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
    """An empty database one revision short of the invite code."""
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


@pytest.fixture()
def scripted_codes(monkeypatch):
    """Makes the migration's code generator emit given values, in order.

    It builds each code one secrets.choice() at a time, so feeding the choices
    decides the codes. Patched on the module rather than on the migration: the
    version scripts are loaded by alembic's own importer, and a copy imported
    here would be a different module object with a different generator in it.
    """

    def script(*codes: str) -> None:
        characters = iter("".join(codes))
        monkeypatch.setattr(secrets, "choice", lambda _alphabet: next(characters))

    return script


def _seed_church(engine, church_id: str, name: str, *, members: int = 1) -> None:
    """A church from before the invite code, with `members` accounts in it."""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO churches (id, name, timezone, created_at) VALUES (:id, :name, 'Asia/Seoul', now())"),
            {"id": church_id, "name": name},
        )
        for index in range(members):
            conn.execute(
                text(
                    "INSERT INTO users (id, church_id, email, name, role, created_at) "
                    "VALUES (:id, :church_id, :email, :name, 'member', now() + (:offset * interval '1 second'))"
                ),
                {
                    "id": f"{church_id}-u{index}",
                    "church_id": church_id,
                    "email": f"{church_id}-{index}@example.com",
                    "name": f"member {index}",
                    "offset": index,
                },
            )


def _codes(engine) -> dict[str, str]:
    with engine.connect() as conn:
        return {row[0]: row[1] for row in conn.execute(text("SELECT id, join_code FROM churches"))}


def _upgrade() -> None:
    command.upgrade(_alembic_config(), "head")


def _downgrade_one() -> None:
    command.downgrade(_alembic_config(), "-1")


def test_upgrade_should_give_every_church_its_own_join_code(migration_db):
    _seed_church(migration_db, "church-a", "가교회")
    _seed_church(migration_db, "church-b", "나교회")

    _upgrade()

    codes = _codes(migration_db)
    assert len(codes) == 2
    assert len(set(codes.values())) == 2
    for code in codes.values():
        # The same shape the application generator emits: eight characters with
        # no l/1/o/0, because a person reads this off one screen and types it
        # into another.
        assert len(code) == 8
        assert set(code) <= ALPHABET


def test_upgrade_should_refuse_a_church_with_nobody_to_promote(migration_db):
    _seed_church(migration_db, "church-staffed", "가교회")
    _seed_church(migration_db, "church-empty", "빈교회", members=0)

    with pytest.raises(RuntimeError) as raised:
        _upgrade()

    # Named, because the operator has to decide what to do with that specific
    # church — merge it, delete it, or give it a member.
    assert "빈교회" in str(raised.value)
    assert "church-empty" in str(raised.value)
    with migration_db.connect() as conn:
        # The whole upgrade is one transaction, so the refusal has to leave the
        # column off entirely. A half-applied migration is worse than none.
        applied = conn.execute(text("SELECT to_regclass('churches')")).scalar()
        assert applied is not None
        columns = conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'churches'")
        ).scalars()
        assert "join_code" not in set(columns)


def test_downgrade_then_upgrade_should_hand_back_the_same_join_codes(migration_db):
    # The invariant the dev-stack check was missing. "Every church has a code"
    # and "no two are alike" both hold after a reissue, so neither one can tell
    # a preserved code from a replaced one — only comparing the values can.
    _seed_church(migration_db, "church-a", "가교회")
    _seed_church(migration_db, "church-b", "나교회")
    _upgrade()
    before = _codes(migration_db)

    _downgrade_one()
    _upgrade()

    assert _codes(migration_db) == before


def test_upgrade_should_not_hand_a_parked_code_to_a_church_founded_meanwhile(
    migration_db, scripted_codes
):
    # A church founded while the revision was un-applied has no parked code and
    # draws a fresh one. That draw has to avoid the codes being handed back, or
    # the unique constraint fails and the whole migration with it.
    #
    # The ids matter. Churches are processed in id order, so `church-a` — the
    # one that draws — is reached before `church-z`, whose code it is about to
    # collide with. The other way round, `church-z`'s code would already be in
    # the collision set for an entirely incidental reason, and the test would
    # pass with the seeding removed. It did, until the ids were swapped.
    _seed_church(migration_db, "church-z", "가교회")
    _upgrade()
    before = _codes(migration_db)
    _downgrade_one()
    _seed_church(migration_db, "church-a", "새교회")
    # The first draw is the collision. Waiting for a real one is not an option
    # at 1 in 32**8 — the guard would never be reached and this test would pass
    # whether or not it existed.
    scripted_codes(before["church-z"], "qrst2345")

    _upgrade()

    after = _codes(migration_db)
    assert after["church-z"] == before["church-z"]
    assert after["church-a"] == "qrst2345"
