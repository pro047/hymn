"""add saved_scores table"""

revision = '46e197553c5c'
down_revision = 'c1f28f6e4ac2'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "saved_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("score_id", sa.String(length=36), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["score_id"], ["scores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "score_id", name="uq_saved_scores_user_score"),
    )
    op.create_index(
        "ix_saved_scores_user_created_at",
        "saved_scores",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_saved_scores_user_use_last_used",
        "saved_scores",
        ["user_id", "use_count", "last_used_at"],
        unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_saved_scores_user_use_last_used", table_name="saved_scores")
    op.drop_index("ix_saved_scores_user_created_at", table_name="saved_scores")
    op.drop_table("saved_scores")
