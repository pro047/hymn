"""Guards the release-N half of dropping `set_items.key` and `set_items.memo`.

Deploy runs `alembic upgrade head` and only then swaps containers
(.github/workflows/deploy.yml), so a column can be dropped safely only once no
deployed image names it -- otherwise the still-running old image SELECTs a
column that is gone, and a rollback to that image 500s for good.

This release removes the mappings; a later one drops the columns. Nothing else
in the suite fails if the mappings come back, so the drop migration would then
break in production with every test green. These tests are that alarm.
"""

from sqlalchemy import select

from app.models import SetItem

DROPPED_COLUMNS = ("key", "memo")


def test_set_item_should_not_map_the_columns_a_later_release_drops():
    mapped = set(SetItem.__mapper__.columns.keys())
    assert mapped.isdisjoint(DROPPED_COLUMNS)


def test_reading_set_items_should_not_name_the_columns_a_later_release_drops():
    # The mapper check above is about the declaration; this is about the SQL an
    # old image would actually send after the drop migration has run.
    compiled = str(select(SetItem).compile())
    for column in DROPPED_COLUMNS:
        assert f"set_items.{column}" not in compiled
