"""make score week optional for saved uploads

Revision ID: f7b8c1d2e3f4
Revises: 46e197553c5c
Create Date: 2026-03-15 18:20:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f7b8c1d2e3f4"
down_revision = "46e197553c5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("scores", "week_of", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    op.alter_column("scores", "week_of", existing_type=sa.Date(), nullable=False)
