"""add password_reset_tokens table

Revision ID: e1b6d4c39a75
Revises: c4f9a1b7e2d3
Create Date: 2026-08-17 00:00:00.000000

Backs the "forgot my password" flow. Nothing is backfilled: a reset link is
minted on request and lives 30 minutes, so an empty table is the correct
starting state and this migration is safe to run against a live deploy.

token_hash is unique so the confirm route can claim a link with one conditional
DELETE, which is what makes it single-use under concurrent requests.
"""

import sqlalchemy as sa
from alembic import op

revision = "e1b6d4c39a75"
down_revision = "c4f9a1b7e2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    # Deleting a user's outstanding links is on the request path; without this
    # each request sequentially scans the table.
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
