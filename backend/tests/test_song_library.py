"""The library is the church's songs, and a Sunday gets a song only from it.

Uploading files a song with no Sunday; placing one files a new usage and leaves
the Sundays the song is already on alone. Everything here is scoped to the
caller's church -- the unauthenticated GET /scores is not the library.
"""

from app.models import Score, Song
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

