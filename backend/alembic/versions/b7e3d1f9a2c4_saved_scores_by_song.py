"""saved_scores belong to a song, not to one week's usage of it

Revision ID: b7e3d1f9a2c4
Revises: a9c4e2f7b1d6
Create Date: 2026-09-27 00:00:00.000000

An entry pointed at the usage it was saved from, with ON DELETE CASCADE, so
taking that one Sunday off deleted the entry while the song was still sung on
others. And since applying now files a new usage instead of moving the old one,
the entry kept reporting the first Sunday it was saved from.

    song_id   NOT NULL, the song -- one entry per (user, song)
    score_id  kept but nullable, ON DELETE SET NULL; no longer mapped

score_id, use_count and last_used_at stop being named by this release's image
and are dropped a release later (the two-release rule in handoff 1-A):
use_count and last_used_at give way to counts read off the song's usages.

song_id is NOT NULL from the start. The previous image does not know the
column, so its save is refused -- during every deploy's window between this
migration and the container swap, and for as long as a rollback lasts -- and
its ORM still cascades a usage delete onto saved_scores. Production held no
saved rows when this was written (2026-09-27, read-only SSM check), so that is
the whole of the exposure, and the constraint does not wait for a release.

Downgrade puts the usage-centric table back. An entry with no score_id has
nowhere to point there (it was NOT NULL) and is dropped: that is every entry
saved after the upgrade, since this image never writes score_id, and every
older one whose usage was deleted since. The rest return to their usage.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e3d1f9a2c4"
down_revision = "a9c4e2f7b1d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("saved_scores", sa.Column("song_id", sa.String(length=36), nullable=True))
    op.execute(
        "UPDATE saved_scores s SET song_id = sc.song_id FROM scores sc WHERE sc.id = s.score_id"
    )
    # Two entries for one song cannot become one without choosing whose
    # created_at survives; production and dev both had none, so refuse loudly
    # rather than choose silently -- the deploy guard keeps the old containers.
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM (SELECT user_id, song_id FROM saved_scores "
            "GROUP BY 1, 2 HAVING count(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(f"{duplicates} user/song pairs saved more than once")

    op.alter_column("saved_scores", "song_id", nullable=False)
    op.create_foreign_key(
        "saved_scores_song_id_fkey", "saved_scores", "songs", ["song_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_saved_scores_song_id", "saved_scores", ["song_id"])
    op.drop_constraint("uq_saved_scores_user_score", "saved_scores", type_="unique")
    op.create_unique_constraint("uq_saved_scores_user_song", "saved_scores", ["user_id", "song_id"])

    op.alter_column("saved_scores", "score_id", nullable=True)
    op.drop_constraint("saved_scores_score_id_fkey", "saved_scores", type_="foreignkey")
    op.create_foreign_key(
        "saved_scores_score_id_fkey", "saved_scores", "scores", ["score_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.execute("DELETE FROM saved_scores WHERE score_id IS NULL")
    op.drop_constraint("saved_scores_score_id_fkey", "saved_scores", type_="foreignkey")
    op.create_foreign_key(
        "saved_scores_score_id_fkey", "saved_scores", "scores", ["score_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("saved_scores", "score_id", nullable=False)

    op.drop_constraint("uq_saved_scores_user_song", "saved_scores", type_="unique")
    op.create_unique_constraint("uq_saved_scores_user_score", "saved_scores", ["user_id", "score_id"])
    op.drop_constraint("saved_scores_song_id_fkey", "saved_scores", type_="foreignkey")
    op.drop_index("ix_saved_scores_song_id", table_name="saved_scores")
    op.drop_column("saved_scores", "song_id")
