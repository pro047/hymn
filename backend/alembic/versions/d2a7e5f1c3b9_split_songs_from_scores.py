"""split songs from scores

Revision ID: d2a7e5f1c3b9
Revises: e1b6d4c39a75
Create Date: 2026-08-28 00:00:00.000000

Introduces `songs` as the canonical row for a title a church sings, so a
reupload can update every week that used it instead of only the one it was
filed under. `scores` stays a weekly usage row: its title/file columns are
kept as a snapshot rather than dropped, so this migration loses nothing and a
downgrade hands the app back exactly what it had.

Grouping runs in Python, not SQL. Postgres' own normalize() needs 13+ and the
production engine version was not available to check; more importantly, if
the grouping rule ever needs to change it should not be able to drift between
this file and app.services.song.normalize_title just because one moved to SQL
and the other stayed in Python. 150 production rows make the round trip free.
The normalization rule itself is copied here rather than imported — a
migration has to stay pinned to the rule it ran with, even if the app
function is edited later. test_migration_song_split.py checks the two copies
still agree.
"""

import re
import unicodedata
import uuid

import sqlalchemy as sa
from alembic import op

revision = "d2a7e5f1c3b9"
down_revision = "e1b6d4c39a75"
branch_labels = None
depends_on = None


def _normalize_title(title: str) -> str:
    folded = unicodedata.normalize("NFC", title)
    collapsed = re.sub(r"\s+", "", folded)
    return collapsed.lower()


def _sort_key(row):
    # week_of DESC NULLS LAST, created_at DESC: the representative row is the
    # most recently used one, since that is the file a church is actually
    # filing scores with today (see the 주만 바라볼찌라 case in the design doc).
    week_of = row["week_of"]
    created_at = row["created_at"]
    return (
        week_of is None,
        -(week_of.toordinal() if week_of is not None else 0),
        -created_at.timestamp(),
    )


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "songs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("church_id", sa.String(length=36), nullable=False),
        sa.Column("uploader_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("title_key", sa.String(length=255), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_uri", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["church_id"], ["churches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("church_id", "title_key", name="uq_songs_church_title_key"),
    )
    op.create_index("ix_songs_church_id", "songs", ["church_id"])

    op.add_column("scores", sa.Column("song_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_scores_song_id_songs", "scores", "songs", ["song_id"], ["id"], ondelete="CASCADE"
    )

    rows = (
        bind.execute(
            sa.text(
                "SELECT id, church_id, uploader_id, title, file_url, file_uri, week_of, created_at "
                "FROM scores"
            )
        )
        .mappings()
        .all()
    )
    n_scores = len(rows)

    groups = {}
    for row in rows:
        key = (row["church_id"], _normalize_title(row["title"]))
        groups.setdefault(key, []).append(row)
    n_groups = len(groups)

    song_inserts = []
    score_updates = []
    for (church_id, title_key), members in groups.items():
        representative = sorted(members, key=_sort_key)[0]
        song_id = str(uuid.uuid4())
        created_at = min(member["created_at"] for member in members)
        song_inserts.append(
            {
                "id": song_id,
                "church_id": church_id,
                "uploader_id": representative["uploader_id"],
                "title": representative["title"].strip(),
                "title_key": title_key,
                "file_url": representative["file_url"],
                "file_uri": representative["file_uri"],
                "created_at": created_at,
                "updated_at": created_at,
            }
        )
        for member in members:
            score_updates.append({"score_id": member["id"], "song_id": song_id})

    if song_inserts:
        bind.execute(
            sa.text(
                "INSERT INTO songs "
                "(id, church_id, uploader_id, title, title_key, file_url, file_uri, created_at, updated_at) "
                "VALUES (:id, :church_id, :uploader_id, :title, :title_key, "
                ":file_url, :file_uri, :created_at, :updated_at)"
            ),
            song_inserts,
        )
    if len(song_inserts) != n_groups:
        raise RuntimeError(f"songs 삽입 행수 불일치: {len(song_inserts)} != {n_groups}")

    if score_updates:
        bind.execute(
            sa.text("UPDATE scores SET song_id = :song_id WHERE id = :score_id"),
            score_updates,
        )
    if len(score_updates) != n_scores:
        raise RuntimeError(f"scores 갱신 행수 불일치: {len(score_updates)} != {n_scores}")

    orphaned = bind.execute(sa.text("SELECT count(*) FROM scores WHERE song_id IS NULL")).scalar()
    if orphaned != 0:
        raise RuntimeError(f"song_id 가 비어 있는 scores 행이 {orphaned}개 남았다")

    op.alter_column("scores", "song_id", existing_type=sa.String(length=36), nullable=False)
    op.create_index("ix_scores_song_id", "scores", ["song_id"])


def downgrade() -> None:
    op.drop_index("ix_scores_song_id", table_name="scores")
    op.drop_constraint("fk_scores_song_id_songs", "scores", type_="foreignkey")
    op.drop_column("scores", "song_id")
    op.drop_index("ix_songs_church_id", table_name="songs")
    op.drop_table("songs")
