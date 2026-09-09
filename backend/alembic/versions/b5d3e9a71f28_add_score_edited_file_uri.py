"""add scores.edited_file_uri — the sheet this one week shows

Revision ID: b5d3e9a71f28
Revises: a3f81c2b7d40
Create Date: 2026-09-09 00:00:00.000000

Both the conti screen and the PDF read Song.file_uri today, so every week that
uses a song shows that song's current file. There is no such thing as "this
week's sheet", and an edit made for one Sunday would have nowhere to land that
does not also rewrite the weeks before it -- including services already held.

A new column rather than reusing scores.file_uri, which looks unused but is
not: it records what each usage was *filed* with, and the song-split downgrade
restores the old table from it (test_migration_song_split, case 11 -- "the
snapshots never moved"). Overwriting it to mean "what this week displays"
would destroy that record and make the downgrade lossy. The two facts are
genuinely different, so they get two columns:

    file_uri         what this usage was filed with   (history, never rewritten)
    edited_file_uri  what this week displays instead  (NULL until someone edits)

NULL everywhere on arrival, and the read is coalesce(edited_file_uri,
Song.file_uri), so rendering is byte-identical to before this migration until
an edit is saved -- by construction, not by a backfill that has to be trusted.
"""

import sqlalchemy as sa
from alembic import op

revision = "b5d3e9a71f28"
down_revision = "a3f81c2b7d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scores", sa.Column("edited_file_uri", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("scores", "edited_file_uri")
