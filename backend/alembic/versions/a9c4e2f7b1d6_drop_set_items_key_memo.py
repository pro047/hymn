"""drop set_items.key and set_items.memo

Revision ID: a9c4e2f7b1d6
Revises: d8a41c6f2b93
Create Date: 2026-09-22 00:00:00.000000

The second half of a two-release drop. The first (8c6ac7f, shipped from
52f716b on) took the columns out of the mapping, so no image that can still be
deployed or rolled back to names them -- deploy runs this migration before it
swaps containers, and an image that SELECTed a dropped column would 500 for
good. tests/test_set_item_unmapped_columns.py keeps the mapping from coming
back.

Production held no data in either column when this was written (2026-09-22,
read-only check over SSM: 170 rows, key 0 filled, memo 0 filled), so the drop
loses nothing. Downgrade puts the columns back as they were, empty: a drop
cannot be undone for data, only for shape.
"""

import sqlalchemy as sa
from alembic import op

revision = "a9c4e2f7b1d6"
down_revision = "d8a41c6f2b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("set_items", "memo")
    op.drop_column("set_items", "key")


def downgrade() -> None:
    op.add_column("set_items", sa.Column("key", sa.String(length=32), nullable=True))
    op.add_column("set_items", sa.Column("memo", sa.String(length=1024), nullable=True))
