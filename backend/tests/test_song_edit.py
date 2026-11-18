"""Editing a song from the library: PATCH /songs/{id} and POST /songs/{id}/file.

The library is where a song lives, so it is where its title and file are fixed,
whether or not any Sunday uses it. A change is copied into the Sundays the song
is placed on from then on; a Sunday it is already placed on keeps its own copy
of the title and file, and never loses an edit drawn on it.
"""

import re
from uuid import uuid4

import pytest

from app.models import Score, Song
from app.schemas.song import SongLibraryItem
from test_song_split import OTHER_CHURCH, _register, _week

TITLE_TAKEN = {"detail": "같은 제목의 곡이 이미 있습니다."}
BAD_KEY = {"detail": "잘못된 파일 경로입니다."}
SONG_NOT_FOUND = {"detail": "Song not found"}
FILE_REQUEST = {"filename": "rescan.png", "content_type": "image/png"}


def _upload(client, headers, title: str) -> str:
    response = client.post(
        "/songs",
        json={"title": title, "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["song_id"]


def _place(client, headers, song_id: str, week: str) -> str:
    response = client.post(f"/songs/{song_id}/usages", json={"week_of": week}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def _patch(client, headers, song_id: str, body: dict):
    return client.patch(f"/songs/{song_id}", json=body, headers=headers)


def _library(client, headers) -> list[dict]:
    response = client.get("/songs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _listed(client, headers, song_id: str) -> dict:
    [item] = [item for item in _library(client, headers) if item["song_id"] == song_id]
    return item


def _church_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["church_id"]


def _scores(client, headers) -> dict[str, dict]:
    response = client.get("/scores", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


def _conti_titles(client, headers, week: str) -> list[str]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for page in response.json()["pages"] for item in page]


# Read without refresh(): the app shares this session (conftest.client), so a
# route that assigned in memory and then refused would show here -- refreshing
# from the database would hide exactly that.
def _song_state(db_session, song_id: str) -> tuple:
    song = db_session.get(Song, song_id)
    return (song.title, song.title_key, song.file_uri, song.file_url)


def _usage_state(db_session, score_id: str) -> tuple:
    score = db_session.get(Score, score_id)
    return (
        score.title,
        score.file_uri,
        score.file_url,
        score.edited_file_uri,
        score.edit_doc,
        score.edit_source_uri,
    )


# --- AC-1: a song no Sunday uses can be renamed -------------------------------


def test_renaming_an_unplaced_song_should_return_the_new_title_with_no_use_AC_1(client):
    # Arrange — uploaded to the library and never placed (AC-1)
    headers = _register(client)
    song_id = _upload(client, headers, "올리기만 한 곡")

    # Act
    response = _patch(client, headers, song_id, {"title": "고친 제목"})

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["song_id"] == song_id
    assert body["title"] == "고친 제목"
    assert body["use_count"] == 0
    assert body["last_week_of"] is None
    assert _listed(client, headers, song_id)["title"] == "고친 제목"


def test_renaming_should_store_the_title_stripped_AC_1(client):
    # Arrange — the stored title is stripped, as rename_song does (AC-1 boundary)
    headers = _register(client)
    song_id = _upload(client, headers, "앞뒤 공백")

    # Act
    response = _patch(client, headers, song_id, {"title": "  고친 제목  "})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "고친 제목"
    assert _listed(client, headers, song_id)["title"] == "고친 제목"


# --- AC-2: the answer is the library's own row --------------------------------


def test_the_patch_answer_should_equal_the_librarys_row_for_that_song_AC_2(client):
    # Arrange — placed on two Sundays, with a second song beside it (AC-2)
    headers = _register(client)
    song_id = _upload(client, headers, "두 번 쓴 곡")
    _place(client, headers, song_id, _week(0))
    _place(client, headers, song_id, _week(2))
    _upload(client, headers, "옆의 곡")

    # Act
    response = _patch(client, headers, song_id, {"title": "두 번 쓴 곡 (고침)"})

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(SongLibraryItem.model_fields)
    assert len(body) == 8
    assert body["use_count"] == 2
    assert body["last_week_of"] == _week(2)
    listed = _listed(client, headers, song_id)
    without_url = {key: value for key, value in body.items() if key != "download_url"}
    assert without_url == {key: value for key, value in listed.items() if key != "download_url"}


def test_a_weekless_legacy_usage_should_not_count_in_the_patch_answer_AC_2(client, db_session):
    # Arrange — the same "used means on a Sunday" rule as the list (AC-2 boundary)
    headers = _register(client)
    song_id = _upload(client, headers, "옛 보관곡")
    legacy_id = _place(client, headers, song_id, _week(0))
    _place(client, headers, song_id, _week(1))
    legacy = db_session.get(Score, legacy_id)
    legacy.week_of = None
    db_session.commit()

    # Act
    response = _patch(client, headers, song_id, {"title": "옛 보관곡 (고침)"})

    # Assert
    assert response.status_code == 200, response.text
    assert (response.json()["use_count"], response.json()["last_week_of"]) == (1, _week(1))


def test_another_churchs_usage_should_not_count_in_the_patch_answer_AC_2(client, db_session):
    # Arrange — a usage row of the same song filed under another church id
    # must not leak into the count (AC-2 boundary: the church filter on usages)
    other = _register(client, OTHER_CHURCH)
    other_church = _church_id(client, other)
    headers = _register(client)
    song_id = _upload(client, headers, "격리곡")
    score_id = _place(client, headers, song_id, _week(0))
    _place(client, headers, song_id, _week(1))
    stray = db_session.get(Score, score_id)
    stray.church_id = other_church
    db_session.commit()

    # Act
    response = _patch(client, headers, song_id, {"title": "격리곡 (고침)"})

    # Assert
    assert response.status_code == 200, response.text
    assert (response.json()["use_count"], response.json()["last_week_of"]) == (1, _week(1))


def test_editing_should_not_move_the_song_in_the_librarys_order_AC_2(client):
    # Arrange — newest first; an edit is not a new upload
    headers = _register(client)
    older = _upload(client, headers, "먼저 올린 곡")
    newer = _upload(client, headers, "나중 올린 곡")

    # Act
    response = _patch(client, headers, older, {"title": "먼저 올린 곡 (고침)"})

    # Assert
    assert response.status_code == 200, response.text
    assert [item["song_id"] for item in _library(client, headers)] == [newer, older]


# --- AC-3: a body that asks for nothing, or too much, is refused --------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": None},
        {"title": None, "file_uri": None},
        {"title": ""},
        {"title": "가" * 256},
        {"file_uri": "x" * 1025},
    ],
    ids=["empty", "null-title", "both-null", "blank-title", "title-256", "file_uri-1025"],
)
def test_an_invalid_body_should_return_422_and_change_nothing_AC_3(client, db_session, body):
    # Arrange (AC-3)
    headers = _register(client)
    song_id = _upload(client, headers, "그대로인 곡")
    before = _song_state(db_session, song_id)

    # Act
    response = _patch(client, headers, song_id, body)

    # Assert
    assert response.status_code == 422, response.text
    assert _song_state(db_session, song_id) == before


def test_the_longest_allowed_title_should_be_accepted_AC_3(client):
    # Arrange — 255 is the edge of the 1..255 rule (AC-3 boundary)
    headers = _register(client)
    song_id = _upload(client, headers, "짧은 곡")

    # Act
    response = _patch(client, headers, song_id, {"title": "가" * 255})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "가" * 255


# --- AC-4: a title the church already has --------------------------------------


def test_renaming_to_another_songs_title_should_return_409_and_keep_both_AC_4(client, db_session):
    # Arrange (AC-4)
    headers = _register(client)
    taken = _upload(client, headers, "라마바")
    song_id = _upload(client, headers, "다른 곡")

    # Act — the same title once spaces are ignored
    response = _patch(client, headers, song_id, {"title": " 라 마바 "})

    # Assert
    assert response.status_code == 409, response.text
    assert response.json() == TITLE_TAKEN
    assert db_session.get(Song, taken).title == "라마바"
    assert _listed(client, headers, taken)["title"] == "라마바"
    assert _listed(client, headers, song_id)["title"] == "다른 곡"


def test_a_taken_title_should_also_leave_the_file_alone_AC_4(client, db_session):
    # Arrange — title and a valid file in one request; the 409 must win whole
    headers = _register(client)
    church_id = _church_id(client, headers)
    _upload(client, headers, "라마바")
    song_id = _upload(client, headers, "다른 곡")
    before = _song_state(db_session, song_id)

    # Act
    response = _patch(
        client,
        headers,
        song_id,
        {"title": "라마바", "file_uri": f"scores/{church_id}/new.png"},
    )

    # Assert
    assert response.status_code == 409, response.text
    assert _song_state(db_session, song_id) == before


# --- AC-5: respacing its own title, and other churches' titles ----------------


def test_respacing_a_songs_own_title_should_be_allowed_AC_5(client, db_session):
    # Arrange (AC-5)
    headers = _register(client)
    song_id = _upload(client, headers, "참아름다워라")

    # Act
    response = _patch(client, headers, song_id, {"title": "참 아름다워라"})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "참 아름다워라"
    assert db_session.query(Song).count() == 1


def test_resending_the_same_title_should_be_allowed_AC_5(client):
    # Arrange — unchanged title is not a collision with itself (AC-5 boundary)
    headers = _register(client)
    song_id = _upload(client, headers, "같은 제목")

    # Act
    response = _patch(client, headers, song_id, {"title": "같은 제목"})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "같은 제목"


def test_another_churchs_title_should_not_block_a_rename_AC_5(client):
    # Arrange (AC-5)
    other = _register(client, OTHER_CHURCH)
    _upload(client, other, "참 아름다워라")
    headers = _register(client)
    song_id = _upload(client, headers, "참아름다워라")

    # Act
    response = _patch(client, headers, song_id, {"title": "참 아름다워라"})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "참 아름다워라"
    assert [item["title"] for item in _library(client, other)] == ["참 아름다워라"]


# --- AC-6: a library rename does not reach Sundays already placed -------------


def test_a_library_rename_should_not_show_on_sundays_already_placed_AC_6(client, db_session):
    # Arrange (AC-6)
    headers = _register(client)
    song_id = _upload(client, headers, "옛 제목")
    first = _place(client, headers, song_id, _week(0))
    second = _place(client, headers, song_id, _week(1))

    # Act
    response = _patch(client, headers, song_id, {"title": "새 제목"})

    # Assert — the usage rows keep their copy
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "새 제목"
    for score_id in (first, second):
        score = db_session.get(Score, score_id)
        db_session.refresh(score)
        assert score.title == "옛 제목"
    # Assert — every read of those Sundays shows the title they were placed with
    listed = _scores(client, headers)
    assert [listed[first]["title"], listed[second]["title"]] == ["옛 제목", "옛 제목"]
    assert _conti_titles(client, headers, _week(0)) == ["옛 제목"]
    assert _conti_titles(client, headers, _week(1)) == ["옛 제목"]
    # Assert — a Sunday placed after the rename copies the new title
    third = _place(client, headers, song_id, _week(2))
    assert _scores(client, headers)[third]["title"] == "새 제목"
    assert _conti_titles(client, headers, _week(2)) == ["새 제목"]


# --- AC-7: only a key this church may name ------------------------------------


@pytest.mark.parametrize(
    "make_key",
    [
        lambda own, other: f"scores/{other}/x.png",
        lambda own, other: f"scores/{own}/../{other}/x.png",
        lambda own, other: f"scores/{own}/a/b.png",
        lambda own, other: "a.pdf",
        lambda own, other: f"scores/{own}/..",
        lambda own, other: f"scores/{own}/",
    ],
    ids=["other-church", "dot-dot", "nested", "legacy", "parent", "empty-name"],
)
def test_a_key_outside_the_churchs_folder_should_return_400_AC_7(client, db_session, make_key):
    # Arrange (AC-7)
    other = _register(client, OTHER_CHURCH)
    other_church = _church_id(client, other)
    headers = _register(client)
    own_church = _church_id(client, headers)
    song_id = _upload(client, headers, "키 검사곡")
    before = _song_state(db_session, song_id)

    # Act
    response = _patch(client, headers, song_id, {"file_uri": make_key(own_church, other_church)})

    # Assert
    assert response.status_code == 400, response.text
    assert response.json() == BAD_KEY
    assert _song_state(db_session, song_id) == before


def test_a_bad_key_should_leave_the_title_alone_too_AC_7(client, db_session):
    # Arrange — the title is valid on its own; the key check must run before it
    other = _register(client, OTHER_CHURCH)
    other_church = _church_id(client, other)
    headers = _register(client)
    song_id = _upload(client, headers, "원래 제목")
    before = _song_state(db_session, song_id)

    # Act
    response = _patch(
        client,
        headers,
        song_id,
        {"title": "새 제목", "file_uri": f"scores/{other_church}/x.png"},
    )

    # Assert
    assert response.status_code == 400, response.text
    assert response.json() == BAD_KEY
    assert _song_state(db_session, song_id) == before
    assert _listed(client, headers, song_id)["title"] == "원래 제목"


# --- AC-8: a library file swap does not reach Sundays already placed ----------


def test_replacing_the_file_should_not_show_on_sundays_already_placed_AC_8(client, db_session):
    # Arrange (AC-8)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "파일 교체곡")
    first = _place(client, headers, song_id, _week(0))
    second = _place(client, headers, song_id, _week(1))
    snapshots = {score_id: _usage_state(db_session, score_id) for score_id in (first, second)}
    old_key = db_session.get(Song, song_id).file_uri
    key = f"scores/{church_id}/new.png"

    # Act
    response = _patch(client, headers, song_id, {"file_uri": key})

    # Assert — the song now points at the new file
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_uri"] == key
    assert body["file_url"].endswith(key)
    assert key in body["download_url"]
    assert body["title"] == "파일 교체곡"
    # Assert — both Sundays keep the file they were placed with
    listed = _scores(client, headers)
    for score_id in (first, second):
        assert listed[score_id]["file_uri"] == old_key
        assert old_key in listed[score_id]["download_url"]
        assert key not in listed[score_id]["download_url"]
    # Assert — and neither usage row was rewritten
    for score_id in (first, second):
        assert _usage_state(db_session, score_id) == snapshots[score_id]


def test_title_and_file_in_one_request_should_both_change_AC_8(client):
    # Arrange — both fields at once (AC-8 / AC-1 together)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "둘 다 고칠 곡")
    key = f"scores/{church_id}/both.png"

    # Act
    response = _patch(client, headers, song_id, {"title": "둘 다 고친 곡", "file_uri": key})

    # Assert
    assert response.status_code == 200, response.text
    listed = _listed(client, headers, song_id)
    assert (listed["title"], listed["file_uri"]) == ("둘 다 고친 곡", key)


def test_a_title_only_patch_should_keep_the_file_AC_8(client, db_session):
    # Arrange — an absent file_uri means "leave it", not "clear it"
    headers = _register(client)
    song_id = _upload(client, headers, "제목만 고칠 곡")
    _, _, file_uri, file_url = _song_state(db_session, song_id)

    # Act
    response = _patch(client, headers, song_id, {"title": "제목만 고친 곡"})

    # Assert
    assert response.status_code == 200, response.text
    assert (response.json()["file_uri"], response.json()["file_url"]) == (file_uri, file_url)


def test_a_file_only_patch_should_keep_the_title_AC_8(client, db_session):
    # Arrange — an absent title means "leave it"
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "제목 유지곡")

    # Act
    response = _patch(client, headers, song_id, {"title": None, "file_uri": f"scores/{church_id}/f.png"})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "제목 유지곡"
    assert db_session.get(Song, song_id).title == "제목 유지곡"


# --- AC-9: an edit drawn on one Sunday survives the new file ------------------


def test_replacing_the_file_should_keep_the_edit_drawn_on_one_sunday_AC_9(client, db_session):
    # Arrange — two Sundays, only the first one edited (AC-9)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "편집된 곡")
    edited_id = _place(client, headers, song_id, _week(0))
    plain_id = _place(client, headers, song_id, _week(1))
    old_key = db_session.get(Song, song_id).file_uri
    drawn = f"scores/{church_id}/edits/drawn.png"
    doc = {"objects": [{"type": "path"}]}
    edited = db_session.get(Score, edited_id)
    edited.edited_file_uri = drawn
    edited.edit_doc = doc
    edited.edit_source_uri = old_key
    db_session.commit()
    edited_before = _usage_state(db_session, edited_id)
    plain_before = _usage_state(db_session, plain_id)
    new_key = f"scores/{church_id}/new.png"

    # Act
    response = _patch(client, headers, song_id, {"file_uri": new_key})

    # Assert — neither usage row moved, the edit included
    assert response.status_code == 200, response.text
    assert _usage_state(db_session, edited_id) == edited_before
    assert _usage_state(db_session, plain_id) == plain_before
    assert edited_before[3:] == (drawn, doc, old_key)
    # Assert — the editor still opens that Sunday's edit
    opened = client.get(f"/scores/{edited_id}/edit", headers=headers)
    assert opened.status_code == 200, opened.text
    assert (opened.json()["edited_file_uri"], opened.json()["edit_doc"]) == (drawn, doc)
    # Assert — the edited Sunday shows its edit; the other keeps its own old file
    listed = _scores(client, headers)
    assert drawn in listed[edited_id]["download_url"]
    assert new_key not in listed[edited_id]["download_url"]
    assert old_key in listed[plain_id]["download_url"]
    assert new_key not in listed[plain_id]["download_url"]
    assert listed[edited_id]["file_uri"] == old_key
    assert listed[plain_id]["file_uri"] == old_key


# --- AC-10: signing an upload for a song --------------------------------------


def test_signing_a_file_upload_should_mint_a_fresh_key_and_change_nothing_AC_10(client, db_session):
    # Arrange — placed once, so a stray usage write would show in the count (AC-10)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "다시 스캔할 곡")
    _place(client, headers, song_id, _week(0))
    before = _song_state(db_session, song_id)
    usages_before = db_session.query(Score).count()

    # Act
    first = client.post(f"/songs/{song_id}/file", json=FILE_REQUEST, headers=headers)
    second = client.post(f"/songs/{song_id}/file", json=FILE_REQUEST, headers=headers)

    # Assert
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    pattern = rf"^scores/{re.escape(church_id)}/[0-9a-f-]{{36}}\.png$"
    assert re.match(pattern, first.json()["s3_key"]), first.json()
    assert re.match(pattern, second.json()["s3_key"]), second.json()
    assert first.json()["upload_url"] != ""
    assert isinstance(first.json()["upload_url"], str)
    assert first.json()["s3_key"] != second.json()["s3_key"]
    assert _song_state(db_session, song_id) == before
    assert db_session.query(Score).count() == usages_before


def test_signing_should_follow_the_files_extension_AC_10(client):
    # Arrange — the extension comes from the filename, as for POST /scores/{id}/file
    headers = _register(client)
    church_id = _church_id(client, headers)
    song_id = _upload(client, headers, "JPG 곡")

    # Act
    response = client.post(
        f"/songs/{song_id}/file",
        json={"filename": "photo.jpg", "content_type": "image/jpeg"},
        headers=headers,
    )

    # Assert
    assert response.status_code == 200, response.text
    assert re.match(rf"^scores/{re.escape(church_id)}/[0-9a-f-]{{36}}\.jpg$", response.json()["s3_key"])


def test_signing_should_work_for_a_song_no_sunday_uses_AC_10(client):
    # Arrange (AC-10)
    headers = _register(client)
    song_id = _upload(client, headers, "미배치곡")

    # Act
    response = client.post(f"/songs/{song_id}/file", json=FILE_REQUEST, headers=headers)

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["s3_key"]


@pytest.mark.parametrize("body", [{"filename": ""}, {}], ids=["blank-filename", "empty"])
def test_signing_with_no_filename_should_return_422_AC_10(client, body):
    # Arrange (AC-10)
    headers = _register(client)
    song_id = _upload(client, headers, "파일명 없는 곡")

    # Act
    response = client.post(f"/songs/{song_id}/file", json=body, headers=headers)

    # Assert
    assert response.status_code == 422, response.text


def test_the_signed_key_should_be_accepted_by_the_patch_AC_10(client):
    # Arrange — the two routes are one flow: sign, PUT, then PATCH that key
    headers = _register(client)
    song_id = _upload(client, headers, "흐름곡")
    key = client.post(f"/songs/{song_id}/file", json=FILE_REQUEST, headers=headers).json()["s3_key"]

    # Act
    response = _patch(client, headers, song_id, {"file_uri": key})

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["file_uri"] == key


# --- AC-11: no token, and another church's song -------------------------------


ROUTES = [
    ("PATCH", "", {"title": "탈취"}),
    ("POST", "/file", FILE_REQUEST),
]


@pytest.mark.parametrize("method,suffix,body", ROUTES, ids=["PATCH", "POST file"])
def test_without_a_token_should_return_401_AC_11(client, db_session, method, suffix, body):
    # Arrange (AC-11)
    headers = _register(client)
    song_id = _upload(client, headers, "토큰 없는 곡")
    before = _song_state(db_session, song_id)

    # Act
    response = client.request(method, f"/songs/{song_id}{suffix}", json=body)

    # Assert
    assert response.status_code == 401, response.text
    assert _song_state(db_session, song_id) == before


@pytest.mark.parametrize("method,suffix,body", ROUTES, ids=["PATCH", "POST file"])
def test_another_churchs_song_should_look_like_no_song_at_all_AC_11(client, db_session, method, suffix, body):
    # Arrange (AC-11)
    owner = _register(client)
    song_id = _upload(client, owner, "주인 곡")
    outsider = _register(client, OTHER_CHURCH)
    before = _song_state(db_session, song_id)

    # Act
    real = client.request(method, f"/songs/{song_id}{suffix}", json=body, headers=outsider)
    missing = client.request(method, f"/songs/{uuid4()}{suffix}", json=body, headers=outsider)

    # Assert
    assert real.status_code == 404, real.text
    assert real.json() == SONG_NOT_FOUND
    assert (missing.status_code, missing.json()) == (real.status_code, real.json())
    assert _song_state(db_session, song_id) == before
    assert _listed(client, owner, song_id)["title"] == "주인 곡"
