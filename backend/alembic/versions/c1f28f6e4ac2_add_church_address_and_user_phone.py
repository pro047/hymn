"""add church address and user phone

Revision ID: c1f28f6e4ac2
Revises: 9ad38e6a12b4
Create Date: 2026-02-14 18:25:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c1f28f6e4ac2"
down_revision = "9ad38e6a12b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("churches", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "phone")
    op.drop_column("churches", "address")
