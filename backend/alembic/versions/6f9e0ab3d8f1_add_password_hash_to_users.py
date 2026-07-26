"""add password_hash column to users

Revision ID: 6f9e0ab3d8f1
Revises: 0e8ce8cf9b96
Create Date: 2026-02-14 17:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "6f9e0ab3d8f1"
down_revision = "0e8ce8cf9b96"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
