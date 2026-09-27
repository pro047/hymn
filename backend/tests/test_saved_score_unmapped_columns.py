"""Guards the release-N half of dropping three saved_scores columns.

Deploy runs `alembic upgrade head` and only then swaps containers
(.github/workflows/deploy.yml), so a column can be dropped safely only once no
deployed image names it -- otherwise the still-running old image SELECTs a
column that is gone, and a rollback to that image 500s for good.

Migration b7e3d1f9a2c4 moved the library onto songs and stopped mapping the
usage-era columns; migration 18af83d5c624 dropped them a release later. Before
the drop nothing else in the suite noticed a restored mapping. Now that the
test database is at head, a restored one breaks every test that reads
saved_scores -- and these two are the ones that say why.
"""

from sqlalchemy import select

from app.models import SavedScore

DROPPED_COLUMNS = ("score_id", "use_count", "last_used_at")


def test_saved_score_should_not_map_the_columns_a_later_release_drops():
    mapped = set(SavedScore.__mapper__.columns.keys())
    assert mapped.isdisjoint(DROPPED_COLUMNS)


def test_reading_saved_scores_should_not_name_the_columns_a_later_release_drops():
    # The mapper check above is about the declaration; this is about the SQL an
    # old image would actually send after the drop migration has run.
    compiled = str(select(SavedScore).compile())
    for column in DROPPED_COLUMNS:
        assert f"saved_scores.{column}" not in compiled
