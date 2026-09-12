"""add scores.edit_doc — the editable source of this week's edited sheet

Revision ID: c7e2a9b41d05
Revises: b5d3e9a71f28
Create Date: 2026-09-10 00:00:00.000000

b5d3e9a71f28 gave a week somewhere to hang a *finished* sheet. That is what
conti and the PDF draw, and it is enough for them, but it is a flattened
picture: once "3부" is baked into those pixels there is no moving it, no
erasing it, and no telling it apart from the notes underneath.

So the edit is stored twice, in the two shapes it is actually used in:

    edited_file_uri  the flattened PNG   -- what conti and the PDF draw
    edit_doc         the objects on top  -- what the editor reopens

Editing reopens the *song's own file* as the canvas background and replays
edit_doc over it. Reopening the flattened PNG instead would show every earlier
marking twice: once baked into the background, once as the restored object.

Nullable with no backfill, and nothing reads it yet -- every existing row is
NULL, which the editor reads as "nothing drawn here". The pair is written
together and cleared together, so a row never carries a picture it cannot
reopen.

The column is JSON with a JSONB variant, matching models.Score: postgres is
the only database this runs against, and JSONB there stores parsed rather than
re-parsing on every read. The shape inside is the editor's, not the server's --
see routes/score.py, which stores it opaquely.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7e2a9b41d05"
down_revision = "b5d3e9a71f28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column("edit_doc", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scores", "edit_doc")
