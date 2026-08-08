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


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))


def upgrade() -> None:
    # Added nullable, filled, then tightened: an existing row cannot satisfy a
    # NOT NULL column that has no value yet, so a one-step add would fail on any
    # database that already has churches in it.
    op.add_column("churches", sa.Column("join_code", sa.String(length=16), nullable=True))

    conn = op.get_bind()
    church_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM churches"))]
    # Collisions are vanishingly unlikely at 32^8, but the unique constraint
    # goes on below and a failed migration is a worse trade than a set lookup.
    assigned = set()
    for church_id in church_ids:
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


def downgrade() -> None:
    # The column goes; the promotions stay. This migration keeps no record of
    # which users it promoted, so demoting every leader would also undo any
    # promotion made afterwards by hand — losing data to reverse a schema change.
    op.drop_constraint("uq_churches_join_code", "churches", type_="unique")
    op.drop_column("churches", "join_code")
