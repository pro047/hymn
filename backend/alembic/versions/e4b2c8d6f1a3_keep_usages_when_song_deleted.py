"""keep usages when a song is deleted

Revision ID: e4b2c8d6f1a3
Revises: 0ffde4301ddb
Create Date: 2026-11-18 00:00:00.000000

Deleting a song used to take every Sunday that placed it along (FK CASCADE).
A usage row carries its own copy of title, file and edits, so it is complete
without the song; the FK now empties song_id instead of deleting the row.
Upgrade moves no data. Downgrade refuses while any row has lost its song:
NOT NULL cannot be restored over NULLs, and deleting those rows to make it
pass would be silent data loss.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b2c8d6f1a3"
down_revision = "0ffde4301ddb"
branch_labels = None
depends_on = None

_FK = "fk_scores_song_id_songs"


def upgrade() -> None:
    bind = op.get_bind()
    n_before = bind.execute(sa.text("SELECT count(*) FROM scores")).scalar_one()

    op.drop_constraint(_FK, "scores", type_="foreignkey")
    op.create_foreign_key(_FK, "scores", "songs", ["song_id"], ["id"], ondelete="SET NULL")
    op.alter_column("scores", "song_id", existing_type=sa.String(length=36), nullable=True)

    n_after = bind.execute(sa.text("SELECT count(*) FROM scores")).scalar_one()
    n_null = bind.execute(sa.text("SELECT count(*) FROM scores WHERE song_id IS NULL")).scalar_one()
    if n_after != n_before:
        raise RuntimeError(f"scores 행수 변화: {n_before} -> {n_after}")
    if n_null != 0:
        raise RuntimeError(f"upgrade 가 song_id 를 비웠다: {n_null}행")


def downgrade() -> None:
    # Guard first, before any DDL, so a refusal leaves schema and data as they were.
    n_orphan = op.get_bind().execute(sa.text("SELECT count(*) FROM scores WHERE song_id IS NULL")).scalar_one()
    if n_orphan > 0:
        raise RuntimeError(
            f"song_id 가 비어 있는 scores 행이 {n_orphan}개 있다 — 지우지 않고 멈춘다. "
            "곡을 되살리거나 행을 정리한 뒤 다시 시도할 것"
        )

    # Same name as d2a7e5f1c3b9 created: its downgrade drops the FK by name.
    op.drop_constraint(_FK, "scores", type_="foreignkey")
    op.create_foreign_key(_FK, "scores", "songs", ["song_id"], ["id"], ondelete="CASCADE")
    op.alter_column("scores", "song_id", existing_type=sa.String(length=36), nullable=False)
