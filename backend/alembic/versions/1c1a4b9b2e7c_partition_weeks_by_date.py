"""partition weeks by date (weekly range), adjust FKs"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from alembic import op

revision = "1c1a4b9b2e7c"
down_revision = "8e6c1cda8a6b"
branch_labels = None
depends_on = None


def _create_week_partitions() -> None:
    """Create weekly RANGE partitions for the current and next year, plus default."""
    today = dt.date.today()
    start = dt.date(today.year, 1, 1)
    # Align to Monday of the starting week
    start -= dt.timedelta(days=start.weekday())
    end = dt.date(today.year + 2, 1, 1)

    cursor = start
    while cursor < end:
        nxt = cursor + dt.timedelta(days=7)
        name = f"weeks_p_{cursor.strftime('%Y%m%d')}"
        op.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF weeks_new "
            f"FOR VALUES FROM ('{cursor.isoformat()}') TO ('{nxt.isoformat()}')"
        )
        cursor = nxt

    op.execute("CREATE TABLE IF NOT EXISTS weeks_p_default PARTITION OF weeks_new DEFAULT")


def upgrade() -> None:
    op.add_column("set_items", sa.Column("week_date", sa.Date(), nullable=True))

    # Convert weeks.date from text to date
    op.execute(sa.text("ALTER TABLE weeks ALTER COLUMN date TYPE date USING to_date(date, 'YYYY-MM-DD')"))

    # Backfill week_date on set_items from weeks.date
    op.execute(
        sa.text(
            """
            UPDATE set_items si
            SET week_date = w.date
            FROM weeks w
            WHERE si.week_id = w.id
            """
        )
    )

    op.drop_constraint("set_items_week_id_fkey", "set_items", type_="foreignkey")

    # Partitioned weeks table (RANGE by date) with composite PK (date, id)
    op.create_table(
        "weeks_new",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("date", "id"),
        postgresql_partition_by="RANGE (date)",
    )

    _create_week_partitions()

    op.execute(
        sa.text(
            """
            INSERT INTO weeks_new (date, id, title, created_at)
            SELECT date, id, title, created_at FROM weeks
            """
        )
    )

    op.rename_table("weeks", "weeks_old")
    op.rename_table("weeks_new", "weeks")

    op.create_foreign_key(
        "set_items_week_fk",
        "set_items",
        "weeks",
        ["week_id", "week_date"],
        ["id", "date"],
        ondelete="CASCADE",
    )

    op.alter_column("set_items", "week_date", nullable=False)

    op.drop_table("weeks_old")


def downgrade() -> None:
    op.drop_constraint("set_items_week_fk", "set_items", type_="foreignkey")

    op.create_table(
        "weeks_plain",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO weeks_plain (id, date, title, created_at)
            SELECT id, to_char(date, 'YYYY-MM-DD'), title, created_at FROM weeks
            """
        )
    )

    op.execute("DROP TABLE weeks CASCADE")
    op.rename_table("weeks_plain", "weeks")

    op.drop_column("set_items", "week_date")

    op.create_foreign_key(
        "set_items_week_id_fkey",
        "set_items",
        "weeks",
        ["week_id"],
        ["id"],
        ondelete="CASCADE",
    )
