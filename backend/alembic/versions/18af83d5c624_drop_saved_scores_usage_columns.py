"""drop saved_scores.score_id, use_count and last_used_at

Revision ID: 18af83d5c624
Revises: b7e3d1f9a2c4
Create Date: 2026-09-27 00:00:00.000000

The second half of a two-release drop. b7e3d1f9a2c4 (shipped in c8c68fd) moved
the library onto songs and took these columns out of the mapping, so no image
that can still be deployed or rolled back to names them -- deploy runs this
migration before it swaps containers, and an image that SELECTed a dropped
column would 500 for good. tests/test_saved_score_unmapped_columns.py keeps the
mapping from coming back.

Nothing reads the values any more: score_id is never written since the switch,
and "how often" / "last sung" are counted off the song's usages
(routes/saved_score.py). Downgrade puts the columns back in the shape
b7e3d1f9a2c4 left them, empty: a drop cannot be undone for data, only for
shape. Every score_id comes back NULL, so a further downgrade past
b7e3d1f9a2c4 deletes every entry (its downgrade drops those with no score_id).
"""

import sqlalchemy as sa
from alembic import op

revision = "18af83d5c624"
down_revision = "b7e3d1f9a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_saved_scores_user_use_last_used", table_name="saved_scores")
    op.drop_constraint("saved_scores_score_id_fkey", "saved_scores", type_="foreignkey")
    op.drop_column("saved_scores", "last_used_at")
    op.drop_column("saved_scores", "use_count")
    op.drop_column("saved_scores", "score_id")


def downgrade() -> None:
    op.add_column("saved_scores", sa.Column("score_id", sa.String(length=36), nullable=True))
    op.add_column("saved_scores", sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("saved_scores", sa.Column("last_used_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "saved_scores_score_id_fkey", "saved_scores", "scores", ["score_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "ix_saved_scores_user_use_last_used",
        "saved_scores",
        ["user_id", "use_count", "last_used_at"],
        unique=False,
    )
