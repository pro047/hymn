"""add users.token_version and refresh_tokens.rotated_at

Revision ID: c4f9a1b7e2d3
Revises: a7d3f0c2b915
Create Date: 2026-08-11 00:00:00.000000

Two columns behind the session-invalidation work:

* users.token_version — bumped on a password change or a detected refresh
  replay. Access tokens embed it; a mismatch is a 401. NOT NULL DEFAULT 0 so
  every existing row starts at 0, which is also what tokens minted before this
  deploy resolve to (they carry no tv claim, read as 0), so nothing is logged
  out by the migration itself.

* refresh_tokens.rotated_at — NULL for live tokens, stamped when rotated.
  Nullable with no backfill: every existing row is a live token, which is
  exactly rotated_at IS NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f9a1b7e2d3"
down_revision = "a7d3f0c2b915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "rotated_at")
    op.drop_column("users", "token_version")
