"""add global unique on users.email

Revision ID: 9ad38e6a12b4
Revises: 6f9e0ab3d8f1
Create Date: 2026-02-14 18:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9ad38e6a12b4"
down_revision = "6f9e0ab3d8f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    duplicate_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM (
                SELECT lower(email)
                FROM users
                GROUP BY lower(email)
                HAVING COUNT(*) > 1
            ) AS dup
            """
        )
    ).scalar_one()

    if duplicate_count > 0:
        raise RuntimeError("Cannot add unique constraint: duplicate user emails exist")

    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_users_email", "users", type_="unique")
