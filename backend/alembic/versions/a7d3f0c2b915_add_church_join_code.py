"""add church join code

Revision ID: a7d3f0c2b915
Revises: b3e5a7c9d1f2
Create Date: 2026-08-08 10:00:00.000000
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "a7d3f0c2b915"
down_revision = "b3e5a7c9d1f2"
branch_labels = None
depends_on = None

# A deliberate copy of app.models.generate_join_code rather than an import. A
# migration has to keep producing what it produced the day it ran, years after
# the application has moved on; importing app code would rewrite this backfill
# every time the format changes, and would break outright if the function moves.
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
_LENGTH = 8

# Where downgrade() parks the codes so upgrade() can hand the same ones back.
# It exists only while this revision is un-applied; upgrade() consumes it.
_BACKUP_TABLE = "churches_join_code_backup"


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def _reclaim_parked_codes(conn) -> dict[str, str]:
    """Takes back whatever a previous downgrade parked, and clears the table.

    Without this a rollback followed by a roll-forward mints a new code for
    every church, and every code a leader had already written down or sent to
    somebody stops working. Nothing on any screen would say why: the joiner
    just gets a 403 on a code they were given an hour ago.
    """
    parked = conn.execute(sa.text("SELECT to_regclass(:name)"), {"name": _BACKUP_TABLE}).scalar()
    if parked is None:
        return {}

    codes = {
        row[0]: row[1]
        for row in conn.execute(sa.text(f"SELECT church_id, join_code FROM {_BACKUP_TABLE}"))
    }
    conn.execute(sa.text(f"DROP TABLE {_BACKUP_TABLE}"))
    return codes


def upgrade() -> None:
    # Added nullable, filled, then tightened: an existing row cannot satisfy a
    # NOT NULL column that has no value yet, so a one-step add would fail on any
    # database that already has churches in it.
    op.add_column("churches", sa.Column("join_code", sa.String(length=16), nullable=True))

    conn = op.get_bind()
    restored = _reclaim_parked_codes(conn)
    # Ordered so two runs over the same data behave the same way. Without it the
    # rows arrive in whatever order the scan produces, which decides whether a
    # generated code is drawn before or after the reclaimed one it might collide
    # with — a bug that shows up in half of all runs and in none of the reruns.
    church_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM churches ORDER BY id"))]
    # Collisions are vanishingly unlikely at 32^8, but the unique constraint
    # goes on below and a failed migration is a worse trade than a set lookup.
    # Seeded with the reclaimed codes so a church founded while this revision was
    # un-applied cannot be handed one that already belongs to another church.
    assigned = set(restored.values())
    for church_id in church_ids:
        code = restored.get(church_id)
        if code is None:
            code = _generate_code()
            while code in assigned:
                code = _generate_code()
        assigned.add(code)
        conn.execute(
            sa.text("UPDATE churches SET join_code = :code WHERE id = :id"),
            {"code": code, "id": church_id},
        )

    op.alter_column("churches", "join_code", nullable=False)
    op.create_unique_constraint("uq_churches_join_code", "churches", ["join_code"])

    # Every church with members but nobody in charge gets its earliest signup
    # promoted, so exactly one account can rotate that church's code. Churches
    # that already have a leader are skipped: a second one would be a privilege
    # grant nobody asked for. Ordered by created_at then id so a tie between two
    # accounts registered in the same instant still resolves the same way twice.
    conn.execute(
        sa.text(
            """
            UPDATE users
            SET role = 'leader'
            WHERE id IN (
                SELECT DISTINCT ON (u.church_id) u.id
                FROM users AS u
                WHERE NOT EXISTS (
                    SELECT 1 FROM users AS l
                    WHERE l.church_id = u.church_id AND l.role = 'leader'
                )
                ORDER BY u.church_id, u.created_at, u.id
            )
            """
        )
    )

    # A church with no members has nobody to promote, so it comes out of the
    # step above still leaderless — holding a code that no account can read and
    # no account can rotate. That church is unjoinable from the moment this runs
    # and there is no in-app way back: the invite code is the only door, and its
    # key was issued to nobody.
    #
    # Refused rather than logged. The whole upgrade is one transaction, so
    # raising here leaves the database exactly as it was, and the migration is
    # the last point where a person is still watching. A warning on a deploy
    # that then reports success is a warning nobody reads.
    leaderless = conn.execute(
        sa.text(
            """
            SELECT c.id, c.name
            FROM churches AS c
            WHERE NOT EXISTS (
                SELECT 1 FROM users AS u
                WHERE u.church_id = c.id AND u.role = 'leader'
            )
            ORDER BY c.name, c.id
            """
        )
    ).all()
    if leaderless:
        listed = ", ".join(f"{name} ({church_id})" for church_id, name in leaderless)
        raise RuntimeError(
            "Refusing to lock churches out of their own invite code. These have "
            f"no account that could read or rotate it: {listed}. Give each one a "
            "member to promote, merge it into the church it duplicates, or "
            "delete it, then run this migration again."
        )


def downgrade() -> None:
    # The codes are parked before the column goes, and upgrade() takes them back.
    # Dropping them outright would make a rollback-and-roll-forward reissue every
    # church's code, invalidating every code already handed out — a silent
    # failure at the exact moment attention is on the rollback, not on this.
    conn = op.get_bind()
    conn.execute(sa.text(f"DROP TABLE IF EXISTS {_BACKUP_TABLE}"))
    conn.execute(
        sa.text(f"CREATE TABLE {_BACKUP_TABLE} AS SELECT id AS church_id, join_code FROM churches")
    )

    # The column goes; the promotions stay. This migration keeps no record of
    # which users it promoted, so demoting every leader would also undo any
    # promotion made afterwards by hand — losing data to reverse a schema change.
    op.drop_constraint("uq_churches_join_code", "churches", type_="unique")
    op.drop_column("churches", "join_code")
