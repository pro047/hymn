"""Guards the release-N half of dropping `set_items.key` and `set_items.memo`.

Deploy runs `alembic upgrade head` and only then swaps containers
(.github/workflows/deploy.yml), so a column can be dropped safely only once no
deployed image names it -- otherwise the still-running old image SELECTs a
column that is gone, and a rollback to that image 500s for good.

The mappings came off first; migration a9c4e2f7b1d6 dropped the columns a
release later. Before the drop nothing else in the suite noticed a restored
mapping. Now that the test database is at head, a restored one breaks every
test that reads set_items -- and these two are the ones that say why.
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
