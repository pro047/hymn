"""The library is the church's songs, and a Sunday gets a song only from it.

Uploading files a song with no Sunday; placing one files a new usage and leaves
the Sundays the song is already on alone. Everything here is scoped to the
caller's church -- the unauthenticated GET /scores is not the library.
"""

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.deps import get_object_probe
from app.main import app
from app.models import Score, Song
from app.utils import s3
from test_song_split import OTHER_CHURCH, _register, _week


def _upload(client, headers, title: str, expect: int = 201):
    response = client.post(
        "/songs",
        json={"title": title, "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == expect, response.text
    return response.json()


def _place(client, headers, song_id: str, week: str):
    return client.post(f"/songs/{song_id}/usages", json={"week_of": week}, headers=headers)


def _library(client, headers) -> list[dict]:
    response = client.get("/songs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _conti_titles(client, headers, week: str) -> list[str]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for page in response.json()["pages"] for item in page]


def test_listing_should_return_every_song_of_the_church_newest_first(client):
    # Arrange — one song placed on a Sunday, one never placed
    headers = _register(client)
    placed = _upload(client, headers, "배치한 곡")["song_id"]
    assert _place(client, headers, placed, _week(0)).status_code == 200
    unplaced = _upload(client, headers, "올리기만 한 곡")["song_id"]

    # Act
    library = _library(client, headers)

    # Assert
    assert [item["song_id"] for item in library] == [unplaced, placed]


def test_listing_should_leave_out_another_churchs_songs(client):
    # Arrange
    other = _register(client, OTHER_CHURCH)
    _upload(client, other, "남의 곡")
    headers = _register(client)
    mine = _upload(client, headers, "우리 곡")["song_id"]

    # Act
    library = _library(client, headers)

    # Assert
    assert [item["song_id"] for item in library] == [mine]


def test_listing_without_a_token_should_return_401(client):
    # Act
    response = client.get("/songs")

    # Assert
    assert response.status_code == 401


def test_uploading_should_file_a_song_and_no_sunday(client, db_session):
    # Act
    headers = _register(client)
    body = _upload(client, headers, "새 곡")

    # Assert
    assert body["upload_url"]
    assert db_session.query(Score).count() == 0
    [item] = _library(client, headers)
    assert item["song_id"] == body["song_id"]
    assert (item["use_count"], item["last_week_of"]) == (0, None)


def test_uploading_a_title_the_church_already_has_should_return_409(client, db_session):
    # Arrange
    headers = _register(client)
    _upload(client, headers, "은혜")

    # Act — the same title, spaced and cased differently
    response = client.post(
        "/songs",
        json={"title": " 은혜 ", "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )

    # Assert
    assert response.status_code == 409, response.text
    assert "보관함에서 골라 배치" in response.json()["detail"]
    assert db_session.query(Song).count() == 1


def test_placing_should_file_the_song_on_that_sunday_and_keep_the_others(client):
    # Arrange — a song already on this Sunday
    headers = _register(client)
    song_id = _upload(client, headers, "재사용곡")["song_id"]
    assert _place(client, headers, song_id, _week(0)).status_code == 200

    # Act
    response = _place(client, headers, song_id, _week(1))

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["song_id"] == song_id
    assert _conti_titles(client, headers, _week(1)) == ["재사용곡"]
    assert _conti_titles(client, headers, _week(0)) == ["재사용곡"]


def test_placing_on_a_sunday_that_already_has_the_song_should_return_409(client):
    # Arrange
    headers = _register(client)
    song_id = _upload(client, headers, "중복곡")["song_id"]
    assert _place(client, headers, song_id, _week(0)).status_code == 200

    # Act
    response = _place(client, headers, song_id, _week(0))

    # Assert
    assert response.status_code == 409, response.text
    assert "이미 그 주차" in response.json()["detail"]
    assert _conti_titles(client, headers, _week(0)) == ["중복곡"]


def test_placing_another_churchs_song_should_return_404(client, db_session):
    # Arrange
    other = _register(client, OTHER_CHURCH)
    foreign = _upload(client, other, "남의 곡")["song_id"]
    headers = _register(client)

    # Act
    response = _place(client, headers, foreign, _week(0))

    # Assert
    assert response.status_code == 404, response.text
    assert db_session.query(Score).count() == 0


def test_placing_should_leave_the_edit_on_the_sunday_it_was_drawn_for(client, db_session):
    # Arrange — this Sunday's usage carries an edit
    headers = _register(client)
    song_id = _upload(client, headers, "편집곡")["song_id"]
    score_id = _place(client, headers, song_id, _week(0)).json()["score_id"]
    original = db_session.get(Score, score_id)
    original.edited_file_uri = f"scores/{original.church_id}/edits/drawn.png"
    original.edit_doc = {"objects": []}
    original.edit_source_uri = original.file_uri
    db_session.commit()

    # Act
    new_id = _place(client, headers, song_id, _week(1)).json()["score_id"]

    # Assert — the edit stays where it was drawn; the new Sunday starts clean
    db_session.refresh(original)
    assert original.edited_file_uri is not None
    new = db_session.get(Score, new_id)
    assert (new.edited_file_uri, new.edit_doc, new.edit_source_uri) == (None, None, None)


def test_the_library_should_report_the_latest_sunday_and_how_many_used_it(client):
    # Arrange
    headers = _register(client)
    song_id = _upload(client, headers, "자주곡")["song_id"]
    for week in (_week(0), _week(2), _week(1)):
        assert _place(client, headers, song_id, week).status_code == 200

    # Act
    [item] = _library(client, headers)

    # Assert
    assert item["use_count"] == 3
    assert item["last_week_of"] == _week(2)


def test_taking_a_song_off_a_sunday_should_keep_it_in_the_library(client):
    # Arrange
    headers = _register(client)
    song_id = _upload(client, headers, "남는곡")["song_id"]
    score_id = _place(client, headers, song_id, _week(0)).json()["score_id"]

    # Act
    deleted = client.delete(f"/scores/{score_id}", headers=headers)

    # Assert
    assert deleted.status_code == 204, deleted.text
    [item] = _library(client, headers)
    assert (item["song_id"], item["use_count"]) == (song_id, 0)


def test_a_weekless_legacy_usage_should_not_count_as_a_use(client, db_session):
    # Arrange — older library uploads filed a usage with no Sunday (dev has two)
    headers = _register(client)
    song_id = _upload(client, headers, "옛 보관곡")["song_id"]
    score_id = _place(client, headers, song_id, _week(0)).json()["score_id"]
    legacy = db_session.get(Score, score_id)
    legacy.week_of = None
    db_session.commit()

    # Act
    [item] = _library(client, headers)

    # Assert
    assert (item["use_count"], item["last_week_of"]) == (0, None)


@pytest.fixture()
def missing_objects():
    """Keys in this set are missing from the bucket; everything else exists."""
    missing: set[str] = set()
    app.dependency_overrides[get_object_probe] = lambda: lambda key: key not in missing
    return missing


def test_uploading_a_title_whose_file_never_arrived_should_hand_out_a_new_key(client, db_session, missing_objects):
    # Arrange — the first upload's PUT never happened
    headers = _register(client)
    first = _upload(client, headers, "은혜")
    missing_objects.add(first["s3_key"])

    # Act
    second = _upload(client, headers, "은혜")

    # Assert — the same song, now pointing at a key that can be uploaded to
    assert second["song_id"] == first["song_id"]
    assert second["s3_key"] != first["s3_key"]
    assert second["upload_url"]
    song = db_session.get(Song, first["song_id"])
    assert song.file_uri == second["s3_key"]
    assert song.file_url.endswith(second["s3_key"])
    assert db_session.query(Song).count() == 1


def test_a_healed_song_should_show_its_new_file_on_the_sundays_it_was_placed_on(client, missing_objects):
    # Arrange — placed on a Sunday before anyone noticed the file was missing
    headers = _register(client)
    first = _upload(client, headers, "은혜")
    assert _place(client, headers, first["song_id"], _week(0)).status_code == 200
    missing_objects.add(first["s3_key"])

    # Act
    second = _upload(client, headers, "은혜")

    # Assert
    [listed] = client.get("/scores").json()
    assert listed["file_uri"] == second["s3_key"]


def test_a_legacy_key_should_never_be_replaced_by_an_upload(client, db_session, missing_objects):
    # Arrange — keys from before the s3 branch were never in the bucket
    headers = _register(client)
    song_id = _upload(client, headers, "옛 곡")["song_id"]
    song = db_session.get(Song, song_id)
    song.file_uri = "a.pdf"
    db_session.commit()
    missing_objects.add("a.pdf")

    # Act
    response = client.post(
        "/songs",
        json={"title": "옛 곡", "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )

    # Assert
    assert response.status_code == 409, response.text
    db_session.refresh(song)
    assert song.file_uri == "a.pdf"


def _head_raising(monkeypatch, exc):
    def head_object(**kwargs):
        raise exc

    monkeypatch.setattr(s3.s3_client, "head_object", head_object)


def test_object_exists_should_say_missing_only_on_a_404(monkeypatch):
    _head_raising(monkeypatch, ClientError({"Error": {"Code": "404"}}, "HeadObject"))

    assert s3.object_exists("scores/c/k.png") is False


def test_object_exists_should_count_a_refusal_as_present(monkeypatch):
    # A 403 says nothing about whether the file is there; guessing "missing"
    # would let an upload overwrite it.
    _head_raising(monkeypatch, ClientError({"Error": {"Code": "403"}}, "HeadObject"))

    assert s3.object_exists("scores/c/k.png") is True


def test_object_exists_should_count_a_network_error_as_present(monkeypatch):
    _head_raising(monkeypatch, EndpointConnectionError(endpoint_url="http://s3"))

    assert s3.object_exists("scores/c/k.png") is True
