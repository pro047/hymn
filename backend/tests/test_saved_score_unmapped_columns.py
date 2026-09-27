"""Guards the release-N half of dropping the saved_scores table.

Deploy runs `alembic upgrade head` and only then swaps containers
(.github/workflows/deploy.yml), so a table can be dropped safely only once no
deployed image names it -- otherwise the still-running old image queries a
table that is gone, and a rollback to that image 500s for good.

The library became the church's songs (routes/song.py); 294694b stopped
mapping saved_scores and migration 0ffde4301ddb dropped it a release later.
Before the drop nothing else in the suite noticed a restored mapping. Now the
test database has no such table, so a restored one breaks whatever reads it --
and these two are the ones that say why.
"""

from app.main import app
from app.models import Base


def test_no_model_should_map_the_table_a_later_release_drops():
    mapped_tables = {mapper.persist_selectable.fullname for mapper in Base.registry.mappers}
    assert "saved_scores" not in mapped_tables


def test_no_route_should_serve_the_old_library_paths():
    # The routes are what an old client would still call; they must be gone
    # with the mapping, or they would be the thing naming the table.
    paths = app.openapi()["paths"]
    assert not any(path.startswith("/me/saved-scores") for path in paths)
    assert "post" not in paths["/scores"]
