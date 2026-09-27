"""drop saved_scores

Revision ID: 0ffde4301ddb
Revises: 18af83d5c624
Create Date: 2026-09-28 00:00:00.000000

The second half of a two-release drop. The library became the church's songs
(routes/song.py) and 294694b, shipped in e9d9c34, took the model and every
route off the table, so no image that can still be deployed or rolled back to
names it -- deploy runs this migration before it swaps containers, and an
image that queried a dropped table would 500 for good.
tests/test_saved_score_unmapped_columns.py keeps a mapping from coming back.

The rows go with it: nothing has read them since the library became the
church's songs, which is every song an entry could have pointed at (user
decision 2026-09-27), and production held none when this was written
(2026-09-28, read-only check over SSM: 0 rows). Downgrade puts the table back in the shape
18af83d5c624 left it, empty: a drop cannot be undone for data, only for shape.
"""

import sqlalchemy as sa
from alembic import op

revision = "0ffde4301ddb"
down_revision = "18af83d5c624"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("saved_scores")


def downgrade() -> None:
    op.create_table(
        "saved_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("song_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "song_id", name="uq_saved_scores_user_song"),
    )
    op.create_index("ix_saved_scores_user_created_at", "saved_scores", ["user_id", "created_at"])
    op.create_index("ix_saved_scores_song_id", "saved_scores", ["song_id"])
