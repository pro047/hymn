"""add scores.edit_source_uri — the sheet an edit was drawn over

Revision ID: d8a41c6f2b93
Revises: c7e2a9b41d05
Create Date: 2026-09-11 00:00:00.000000

An edit belongs to one Sunday, and so does the sheet it was drawn on. Those
are two different facts, and until now only the first was stored: reopening
the editor laid the saved objects over the song's *current* file. Replace that
file from any other week and the earlier week's markings come back positioned
for a sheet that is no longer there — the conti still draws the flattened
picture correctly, so nothing looks wrong until the editor is opened, and
saving from there bakes the misplacement in.

    edited_file_uri  the flattened sheet   -- what conti and the PDF draw
    edit_doc         the objects on top    -- what the editor reopens
    edit_source_uri  what they were drawn over

The alternative was to drop every week's edit when a song's file changes,
which throws away work on Sundays nobody asked about (routes/score.py says
why that was refused for this usage too). Recording the background instead
keeps each week whole, which is what "the edit belongs to that week" has to
mean if it means anything.

Nullable with no backfill, and NULL keeps the behaviour that exists today: the
read is coalesce(edit_source_uri, song file), and no row has one yet.
"""

import sqlalchemy as sa
from alembic import op

revision = "d8a41c6f2b93"
down_revision = "c7e2a9b41d05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scores", sa.Column("edit_source_uri", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("scores", "edit_source_uri")
