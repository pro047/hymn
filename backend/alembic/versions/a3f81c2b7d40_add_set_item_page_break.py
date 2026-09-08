"""add set_items.starts_new_page

Revision ID: a3f81c2b7d40
Revises: d2a7e5f1c3b9
Create Date: 2026-09-06 00:00:00.000000

Lets a leader put a page break in a week's conti. Until now the PDF chunked
the week into pages mechanically, two songs at a time, which splits a pair
that is actually sung back to back whenever it lands on an odd boundary —
the very thing the interviews asked for ("곡도 두 개씩 이어서 부르잖아 보통").

A boolean on the item, rather than an explicit page/slot coordinate pair,
because order_no stays the single source of truth for sequence and this flag
only marks where the renderer cuts. A coordinate pair would hold the same
information twice and could drift out of agreement with order_no when a song
is added or moved.

NOT NULL DEFAULT false, so the 160 production rows need no backfill and the
rendering is byte-identical to before this migration until someone sets a
flag.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3f81c2b7d40"
down_revision = "d2a7e5f1c3b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "set_items",
        sa.Column("starts_new_page", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("set_items", "starts_new_page")
