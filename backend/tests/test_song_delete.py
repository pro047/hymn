"""Deleting a song from the library: DELETE /songs/{id}.

The song row goes; every Sunday it was filed on stays. A week keeps its own
copy of the title, the file and any sheet drawn on it, so losing the song only
empties the week's song_id -- the conti, the PDF and the tablet list read on
exactly as before. Nothing is removed from S3: the song and its weeks share the
same object, and removing it would blank the Sundays this route promises to
keep.
"""

import io
from datetime import date, timedelta
from uuid import uuid4

import pytest
from PIL import Image

from app.deps import get_object_reader
from app.main import app
from app.models import Score, Song
from app.utils import s3
from song_helpers import serve_anonymous_scores


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday().isoformat()
NEXT_WEEK = (_this_week_sunday() + timedelta(days=7)).isoformat()

LEADER = {
    "name": "leader",
    "email": "delete-leader@example.com",
    "password": "Password1",
    "church": "Song Delete Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}
OTHER_CHURCH = {**LEADER, "email": "delete-stranger@example.com", "church": "Other Song Delete Church"}

SONG_NOT_FOUND = {"detail": "Song not found"}
LEADER_ONLY_DETAIL = {"detail": "인도자만 할 수 있는 작업입니다."}
# The GET /scores contract hymn_app reads (see test_score_list_scope.SCORE_KEYS).
SCORE_KEYS = {"church_id", "created_at", "download_url", "file_uri", "file_url", "id", "song_id", "title", "week_of"}
# What a score stores; the presigned URL beside them is signed per second.
STORED_SCORE_FIELDS = ("id", "title", "file_url", "file_uri", "week_of", "church_id", "created_at")
EDIT_DOC = {"version": "1", "objects": [{"type": "i-text", "text": "3부", "left": 10, "top": 20}]}


def _signup(client, payload: dict = LEADER) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _headers(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['tokens']['access_token']}"}


def _leader(client, payload: dict = LEADER) -> dict:
    return _headers(_signup(client, payload))


def _upload(client, headers, title: str) -> str:
    response = client.post(
        "/songs",
        json={"title": title, "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["song_id"]


def _place(client, headers, song_id: str, week: str = THIS_WEEK) -> str:
    response = client.post(f"/songs/{song_id}/usages", json={"week_of": week}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def _delete(client, headers, song_id: str):
    return client.delete(f"/songs/{song_id}", headers=headers)


def _library(client, headers) -> list[tuple]:
    response = client.get("/songs", headers=headers)
    assert response.status_code == 200, response.text
    return [(song["song_id"], song["title"], song["use_count"]) for song in response.json()]


def _score(client, headers, score_id: str) -> dict:
    response = client.get(f"/scores/{score_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _stored(score: dict) -> dict:
    return {key: score[key] for key in STORED_SCORE_FIELDS}


def _scores(client, headers=None) -> list[dict]:
    response = client.get("/scores", headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def _edit(client, headers, score_id: str) -> dict:
    response = client.get(f"/scores/{score_id}/edit", headers=headers)
    assert response.status_code == 200, response.text
    return {key: response.json()[key] for key in ("edited_file_uri", "edit_doc")}


def _save_edit(client, headers, score_id: str) -> str:
    signed = client.post(f"/scores/{score_id}/edited-file", headers=headers)
    assert signed.status_code == 200, signed.text
    key = signed.json()["s3_key"]
    saved = client.put(
        f"/scores/{score_id}/edit", json={"edited_file_uri": key, "edit_doc": EDIT_DOC}, headers=headers
    )
    assert saved.status_code == 200, saved.text
    return key


def _conti(client, headers, week: str = THIS_WEEK) -> list[list[tuple]]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [
        [(item["score_id"], item["title"], item["starts_new_page"], item["image_url"] is not None) for item in page]
        for page in response.json()["pages"]
    ]


@pytest.fixture()
def sheet_reader():
    """The PDF route reads each week's file; give it a PNG instead of S3."""
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, "PNG")
    app.dependency_overrides[get_object_reader] = lambda: lambda key: buffer.getvalue()
    yield
    app.dependency_overrides.pop(get_object_reader, None)


class _S3Recorder:
    """Stands in for the boto3 client and writes down every attribute asked of it."""

    def __init__(self):
        self.calls: list[str] = []

    def __getattr__(self, name):
        self.calls.append(name)
        return lambda *args, **kwargs: None


# --- AC-5: the ORM lets go of the weeks too -----------------------------------


# AC-5
def test_deleting_a_song_through_the_orm_should_keep_its_week_with_no_song_id(client, db_session):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    score_id = _place(client, leader, song_id)
    db_session.expire_all()

    # Act
    db_session.delete(db_session.get(Song, song_id))
    db_session.flush()
    db_session.expire_all()

    # Assert
    score = db_session.get(Score, score_id)
    assert score is not None
    assert score.song_id is None
    assert score.title == "은혜"
    assert db_session.get(Song, song_id) is None


# AC-5: the same when the song's weeks were already loaded into the session.
def test_deleting_a_song_whose_weeks_are_loaded_should_keep_them_with_no_song_id(client, db_session):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    first = _place(client, leader, song_id, THIS_WEEK)
    second = _place(client, leader, song_id, NEXT_WEEK)
    db_session.expire_all()
    song = db_session.get(Song, song_id)
    assert sorted(usage.id for usage in song.usages) == sorted([first, second])

    # Act
    db_session.delete(song)
    db_session.flush()
    db_session.expire_all()

    # Assert
    assert [db_session.get(Score, score_id).song_id for score_id in (first, second)] == [None, None]


# --- AC-6: the leader deletes; the rest of the library is untouched -----------


# AC-6
def test_deleting_a_placed_song_should_return_204_and_take_only_that_song(client):
    # Arrange
    leader = _leader(client)
    song_a = _upload(client, leader, "은혜")
    song_b = _upload(client, leader, "평안")
    _place(client, leader, song_a)
    score_b = _place(client, leader, song_b)
    b_before = _stored(_score(client, leader, score_b))

    # Act
    response = _delete(client, leader, song_a)

    # Assert
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert _library(client, leader) == [(song_b, "평안", 1)]
    b_after = _score(client, leader, score_b)
    assert _stored(b_after) == b_before
    assert b_after["song_id"] == song_b


# AC-6: a song no Sunday uses is deleted the same way.
def test_deleting_an_unplaced_song_should_return_204_and_empty_the_library(client):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")

    # Act
    response = _delete(client, leader, song_id)

    # Assert
    assert response.status_code == 204, response.text
    assert _library(client, leader) == []
    assert _scores(client, leader) == []


# AC-6: every Sunday the song was on stays, not just one.
def test_deleting_a_song_placed_on_two_sundays_should_keep_both(client):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    first = _place(client, leader, song_id, THIS_WEEK)
    second = _place(client, leader, song_id, NEXT_WEEK)

    # Act
    response = _delete(client, leader, song_id)

    # Assert
    assert response.status_code == 204, response.text
    listed = _scores(client, leader)
    assert [(item["id"], item["song_id"], item["week_of"]) for item in listed] == [
        (first, None, THIS_WEEK),
        (second, None, NEXT_WEEK),
    ]


# --- AC-7: no token, and a member ---------------------------------------------


# AC-7
def test_deleting_without_a_token_should_return_401_and_keep_the_song(client):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")

    # Act
    response = client.delete(f"/songs/{song_id}")

    # Assert
    assert response.status_code == 401, response.text
    assert _library(client, leader) == [(song_id, "은혜", 0)]


# AC-7
def test_a_member_deleting_should_get_403_and_keep_the_song(client):
    # Arrange
    founded = _signup(client)
    leader = _headers(founded)
    member = _headers(
        _signup(client, {**LEADER, "email": "delete-member@example.com", "join_code": founded["church"]["code"]})
    )
    song_id = _upload(client, leader, "은혜")
    _place(client, leader, song_id)

    # Act
    response = _delete(client, member, song_id)

    # Assert
    assert response.status_code == 403, response.text
    assert response.json() == LEADER_ONLY_DETAIL
    assert _library(client, leader) == [(song_id, "은혜", 1)]


# --- AC-8: another church ------------------------------------------------------


# AC-8
def test_another_churchs_leader_deleting_should_look_like_no_song_at_all(client):
    # Arrange
    owner = _leader(client)
    song_id = _upload(client, owner, "은혜")
    score_id = _place(client, owner, song_id)
    outsider = _leader(client, OTHER_CHURCH)

    # Act
    real = _delete(client, outsider, song_id)
    missing = _delete(client, outsider, str(uuid4()))

    # Assert
    assert real.status_code == 404, real.text
    assert real.json() == SONG_NOT_FOUND
    assert (missing.status_code, missing.json()) == (real.status_code, real.json())
    assert _library(client, owner) == [(song_id, "은혜", 1)]
    assert _score(client, owner, score_id)["song_id"] == song_id


# --- AC-9: the week reads on as before ----------------------------------------


# AC-9
def test_a_deleted_songs_week_should_read_the_same_everywhere_but_song_id(client, sheet_reader):
    # Arrange
    leader = _leader(client)
    song_a = _upload(client, leader, "은혜")
    song_b = _upload(client, leader, "평안")
    score_a = _place(client, leader, song_a)
    score_b = _place(client, leader, song_b)
    _save_edit(client, leader, score_a)

    list_before = _scores(client, leader)
    one_before = _score(client, leader, score_a)
    edit_before = _edit(client, leader, score_a)
    conti_before = _conti(client, leader)
    assert one_before["song_id"] == song_a

    # Act
    response = _delete(client, leader, song_a)

    # Assert
    assert response.status_code == 204, response.text

    list_after = _scores(client, leader)
    assert [item["id"] for item in list_after] == [item["id"] for item in list_before] == [score_a, score_b]
    for before, after in zip(list_before, list_after, strict=True):
        assert set(after) == SCORE_KEYS
        assert _stored(after) == _stored(before)
        assert after["download_url"] is not None
    assert [item["song_id"] for item in list_after] == [None, song_b]

    one_after = _score(client, leader, score_a)
    assert _stored(one_after) == _stored(one_before)
    assert one_after["song_id"] is None
    assert one_after["download_url"] is not None

    assert _edit(client, leader, score_a) == edit_before
    assert edit_before["edit_doc"] == EDIT_DOC
    assert _conti(client, leader) == conti_before

    pdf = client.get(f"/weeks/{THIS_WEEK}/pdf", headers=leader)
    assert pdf.status_code == 200, pdf.text


# AC-9: the tablet's list (no token) keeps its rows, keys and order.
def test_a_deleted_songs_week_should_stay_in_the_tablets_score_list(client, monkeypatch):
    # Arrange
    leader = _leader(client)
    serve_anonymous_scores(monkeypatch, client, leader)
    song_a = _upload(client, leader, "은혜")
    song_b = _upload(client, leader, "평안")
    score_a = _place(client, leader, song_a)
    score_b = _place(client, leader, song_b)
    before = _scores(client)

    # Act
    response = _delete(client, leader, song_a)

    # Assert
    assert response.status_code == 204, response.text
    after = _scores(client)
    assert [item["id"] for item in after] == [score_a, score_b]
    assert [set(item) for item in after] == [SCORE_KEYS, SCORE_KEYS]
    assert [_stored(item) for item in after] == [_stored(item) for item in before]
    assert [item["song_id"] for item in after] == [None, song_b]


# --- AC-10: the week can still be edited --------------------------------------


# AC-10
def test_a_deleted_songs_week_should_still_take_every_week_edit(client):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    score_id = _place(client, leader, song_id)
    assert _delete(client, leader, song_id).status_code == 204

    # Act & Assert — rename the week's copy
    renamed = client.patch(f"/scores/{score_id}", json={"title": "은혜 (2절)"}, headers=leader)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "은혜 (2절)"
    assert renamed.json()["song_id"] is None

    # Act & Assert — draw on it, then clear the drawing
    signed = client.post(f"/scores/{score_id}/edited-file", headers=leader)
    assert signed.status_code == 200, signed.text
    saved = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": signed.json()["s3_key"], "edit_doc": EDIT_DOC},
        headers=leader,
    )
    assert saved.status_code == 200, saved.text
    cleared = client.delete(f"/scores/{score_id}/edit", headers=leader)
    assert cleared.status_code == 200, cleared.text

    # Act & Assert — reorder its Sunday
    ordered = client.patch(
        f"/weeks/{THIS_WEEK}/conti/order", json={"items": [{"score_id": score_id}]}, headers=leader
    )
    assert ordered.status_code == 200, ordered.text

    # Act & Assert — move it to next Sunday
    moved = client.patch(f"/scores/{score_id}", json={"week_of": NEXT_WEEK}, headers=leader)
    assert moved.status_code == 200, moved.text
    assert moved.json()["week_of"] == NEXT_WEEK
    assert moved.json()["song_id"] is None


# --- AC-11: no S3 call ---------------------------------------------------------


# AC-11
def test_deleting_a_song_should_not_touch_s3(client, monkeypatch):
    # Arrange — everything that does reach S3 happens before the recorder goes in.
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    _place(client, leader, song_id)
    recorder = _S3Recorder()
    monkeypatch.setattr(s3, "s3_client", recorder)

    # Act
    response = _delete(client, leader, song_id)

    # Assert
    assert response.status_code == 204, response.text
    assert recorder.calls == []


# --- AC-12: the title is free again --------------------------------------------


# AC-12
def test_uploading_the_deleted_songs_title_again_should_make_a_new_song(client):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    _place(client, leader, song_id)
    assert _delete(client, leader, song_id).status_code == 204

    # Act
    response = client.post(
        "/songs",
        json={"title": "은혜", "filename": "score.png", "content_type": "image/png"},
        headers=leader,
    )

    # Assert
    assert response.status_code == 201, response.text
    new_id = response.json()["song_id"]
    assert new_id != song_id
    assert _library(client, leader) == [(new_id, "은혜", 0)]


# --- AC-13: a deleted song is gone for every song route ------------------------


# AC-13
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("POST", "/usages", {"week_of": NEXT_WEEK}),
        ("PATCH", "", {"title": "되살리기"}),
        ("POST", "/file", {"filename": "rescan.png", "content_type": "image/png"}),
        ("DELETE", "", None),
    ],
    ids=["POST usages", "PATCH", "POST file", "DELETE again"],
)
def test_a_deleted_songs_id_should_be_not_found_on_every_song_route(client, method, suffix, body):
    # Arrange
    leader = _leader(client)
    song_id = _upload(client, leader, "은혜")
    score_id = _place(client, leader, song_id)
    assert _delete(client, leader, song_id).status_code == 204

    # Act
    kwargs = {"json": body} if body is not None else {}
    response = client.request(method, f"/songs/{song_id}{suffix}", headers=leader, **kwargs)

    # Assert
    assert response.status_code == 404, response.text
    assert response.json() == SONG_NOT_FOUND
    assert [item["id"] for item in _scores(client, leader)] == [score_id]
