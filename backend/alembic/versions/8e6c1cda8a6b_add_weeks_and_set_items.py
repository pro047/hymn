"""add weeks and set_items tables plus file_uri on scores"""

import sqlalchemy as sa
from alembic import op

revision = "8e6c1cda8a6b"
down_revision = "da94023e5267"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scores", sa.Column("file_uri", sa.String(length=1024), nullable=True))

    op.create_table(
        "weeks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "set_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("week_id", sa.String(length=36), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.Column("score_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=True),
        sa.Column("memo", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["week_id"], ["weeks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("set_items")
    op.drop_table("weeks")
    op.drop_column("scores", "file_uri")
