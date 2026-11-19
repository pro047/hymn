"""A week reads and writes its own copy of the song (week-copy, AC-1..AC-15).

Placing a song on a Sunday copies the song's title and file into that week's
`scores` row (add_usage). Every read of a week — GET /scores, GET /scores/{id},
the conti, the PDF and the editor — answers from that copy, with the week's
edited sheet first where one exists, and PATCH /scores/{id} rewrites that copy
and nothing else. The library (`songs`) is only ever read when a song is placed
again; the one route that writes both is the heal on re-upload.

The "drifted" states below change the song row behind the weeks' backs, the
way a library edit does, so a read that still goes through the song shows the
drifted value and fails here.
"""

from io import BytesIO
from urllib.parse import unquote

import pytest
from PIL import Image

from app.deps import get_object_probe, get_object_reader
from app.main import app
from app.models import Score, Song
from app.services.song import normalize_title
from song_helpers import serve_anonymous_scores
from test_song_split import CONTRACT_KEYS, OTHER_CHURCH, _register, _week

EDIT_DOC = {"version": "1", "objects": [{"type": "i-text", "text": "3부"}]}


class _Reader:
    """The object reader the PDF route gets instead of S3: records the keys it
    is asked for, in order."""

    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.keys: list[str] = []

    def serve(self, key: str, payload: bytes) -> None:
        self.payloads[key] = payload

    def __call__(self, key: str) -> bytes:
        self.keys.append(key)
        return self.payloads[key]


@pytest.fixture()
def reader():
    stub = _Reader()
    app.dependency_overrides[get_object_reader] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_object_reader, None)


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (300, 400), color).save(buffer, "PNG")
    return buffer.getvalue()


def _church_id(client, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["church_id"]


def _upload(client, headers, title: str) -> dict:
    """{"song_id", "key"} of a freshly uploaded library song."""
    response = client.post(
        "/songs",
        json={"title": title, "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {"song_id": response.json()["song_id"], "key": response.json()["s3_key"]}


def _place(client, headers, song_id: str, week: str) -> str:
    response = client.post(f"/songs/{song_id}/usages", json={"week_of": week}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def _scores(client, headers=None) -> dict[str, dict]:
    response = client.get("/scores", headers=headers or {})
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


def _conti(client, headers, week: str) -> dict[str, dict]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return {item["score_id"]: item for page in response.json()["pages"] for item in page}


def _save_edit(client, headers, score_id: str) -> str:
    """Saves an edit on one week the way the editor does; the edited key."""
    signed = client.post(f"/scores/{score_id}/edited-file", headers=headers)
    assert signed.status_code == 200, signed.text
    key = signed.json()["s3_key"]
    saved = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": key, "edit_doc": EDIT_DOC},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    return key


def _drift_song(db_session, song_id: str, *, title: str | None = None, key: str | None = None) -> None:
    """Changes only the song row, as a library edit would."""
    song = db_session.get(Song, song_id)
    if title is not None:
        song.title = title
        song.title_key = normalize_title(title)
    if key is not None:
        song.file_uri = key
        song.file_url = f"https://example.invalid/{key}"
    db_session.commit()


# Read without refresh(): the app shares this session (conftest.client), so a
# route that assigned in memory and then refused would show here.
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


def _sign_week_file(client, headers, score_id: str) -> str:
    response = client.post(
        f"/scores/{score_id}/file",
        json={"filename": "rescan.png", "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["s3_key"]


# --- AC-1: a library fix does not reach a week already placed ----------------


def test_a_library_fix_should_leave_placed_weeks_and_reach_new_placements_AC_1(client):
    # Arrange — placed once, then the library song gets a new title and file (AC-1)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song = _upload(client, headers, "옛 제목")
    placed = _place(client, headers, song["song_id"], _week(0))
    new_key = f"scores/{church_id}/fixed.png"

    # Act
    fixed = client.patch(
        f"/songs/{song['song_id']}",
        json={"title": "새 제목", "file_uri": new_key},
        headers=headers,
    )
    assert fixed.status_code == 200, fixed.text
    later = _place(client, headers, song["song_id"], _week(1))

    # Assert — the week placed before the fix keeps what it was placed with
    listed = _scores(client, headers)
    before = listed[placed]
    assert before["title"] == "옛 제목"
    assert before["file_uri"] == song["key"]
    assert before["file_url"].startswith("http")
    assert before["file_url"].endswith(song["key"])
    assert song["key"] in unquote(before["download_url"])
    assert new_key not in unquote(before["download_url"])
    # Assert — the week placed after it copies the fixed values
    after = listed[later]
    assert after["title"] == "새 제목"
    assert after["file_uri"] == new_key
    assert after["file_url"].endswith(new_key)
    assert new_key in unquote(after["download_url"])


# --- AC-2: GET /scores reads the copy, edit first ---------------------------


def _edited_and_plain(client, db_session, headers) -> dict:
    """One song on two weeks, the first edited, then the song row drifted."""
    church_id = _church_id(client, headers)
    song = _upload(client, headers, "복사본 곡")
    edited = _place(client, headers, song["song_id"], _week(0))
    plain = _place(client, headers, song["song_id"], _week(1))
    edited_key = _save_edit(client, headers, edited)
    drift_key = f"scores/{church_id}/drifted.png"
    _drift_song(db_session, song["song_id"], title="곡만 바뀐 제목", key=drift_key)
    return {
        "edited": edited,
        "plain": plain,
        "copy_key": song["key"],
        "edited_key": edited_key,
        "drift_key": drift_key,
    }


def test_get_scores_should_serve_the_weeks_copy_and_its_edit_first_AC_2(client, db_session):
    # Arrange (AC-2)
    headers = _register(client)
    state = _edited_and_plain(client, db_session, headers)

    # Act
    listed = _scores(client, headers)

    # Assert — the edited week: edit in download_url, copy in file_uri
    edited = listed[state["edited"]]
    assert state["edited_key"] in unquote(edited["download_url"])
    assert edited["file_uri"] == state["copy_key"]
    assert edited["title"] == "복사본 곡"
    # Assert — the plain week: its copy, never the drifted song
    plain = listed[state["plain"]]
    assert plain["file_uri"] == state["copy_key"]
    assert plain["file_url"].endswith(state["copy_key"])
    assert state["copy_key"] in unquote(plain["download_url"])
    assert state["drift_key"] not in unquote(plain["download_url"])
    assert plain["title"] == "복사본 곡"


def test_a_week_whose_copy_has_no_file_should_list_no_download_url_AC_2(client, db_session):
    # Arrange — a legacy row with no key of its own, while the song still has one (AC-2)
    headers = _register(client)
    song = _upload(client, headers, "파일 없는 주차")
    score_id = _place(client, headers, song["song_id"], _week(0))
    db_session.get(Score, score_id).file_uri = None
    db_session.commit()

    # Act
    item = _scores(client, headers)[score_id]

    # Assert — nothing to sign; the song's key is not borrowed
    assert item["file_uri"] is None
    assert item["download_url"] is None


# --- AC-3: GET /scores/{id} follows the same rule ---------------------------


def test_get_one_score_should_serve_the_weeks_copy_and_its_edit_first_AC_3(client, db_session):
    # Arrange (AC-3)
    headers = _register(client)
    state = _edited_and_plain(client, db_session, headers)

    # Act
    edited = client.get(f"/scores/{state['edited']}", headers=headers)
    plain = client.get(f"/scores/{state['plain']}", headers=headers)

    # Assert — the edited week now answers with its edit
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert state["edited_key"] in unquote(body["download_url"])
    assert body["file_uri"] == state["copy_key"]
    assert body["title"] == "복사본 곡"
    # Assert — the plain week answers with its copy
    assert plain.status_code == 200, plain.text
    body = plain.json()
    assert body["file_uri"] == state["copy_key"]
    assert body["file_url"].endswith(state["copy_key"])
    assert state["copy_key"] in unquote(body["download_url"])
    assert state["drift_key"] not in unquote(body["download_url"])
    assert body["title"] == "복사본 곡"


# --- AC-4 / AC-5: the conti and the PDF read the copy ------------------------


def _drifted_week(client, db_session, reader, headers) -> dict:
    """Two songs on one week, the second edited, then both song rows drifted.
    Every key involved is readable, so a wrong read shows as a wrong key."""
    church_id = _church_id(client, headers)
    plain_song = _upload(client, headers, "첫 곡")
    edited_song = _upload(client, headers, "둘째 곡")
    plain = _place(client, headers, plain_song["song_id"], _week(0))
    edited = _place(client, headers, edited_song["song_id"], _week(0))
    edited_key = _save_edit(client, headers, edited)
    drift_keys = []
    for index, song in enumerate((plain_song, edited_song)):
        drift_key = f"scores/{church_id}/drift-{index}.png"
        _drift_song(db_session, song["song_id"], title=f"바뀐 제목 {index}", key=drift_key)
        drift_keys.append(drift_key)
    for key in (plain_song["key"], edited_song["key"], edited_key, *drift_keys):
        reader.serve(key, _png((200, 30, 30)))
    return {
        "plain": plain,
        "edited": edited,
        "plain_key": plain_song["key"],
        "edited_song_key": edited_song["key"],
        "edited_key": edited_key,
        "drift_keys": drift_keys,
    }


def test_the_conti_should_show_the_weeks_copy_and_its_edit_first_AC_4(client, db_session, reader):
    # Arrange (AC-4)
    headers = _register(client)
    state = _drifted_week(client, db_session, reader, headers)

    # Act
    items = _conti(client, headers, _week(0))

    # Assert — titles are the weeks' copies
    assert items[state["plain"]]["title"] == "첫 곡"
    assert items[state["edited"]]["title"] == "둘째 곡"
    # Assert — the plain week signs its copy, the edited week its edit
    plain_url = unquote(items[state["plain"]]["image_url"])
    edited_url = unquote(items[state["edited"]]["image_url"])
    assert state["plain_key"] in plain_url
    assert state["edited_key"] in edited_url
    for drift_key in state["drift_keys"]:
        assert drift_key not in plain_url
        assert drift_key not in edited_url


def test_the_pdf_should_read_the_weeks_copy_and_its_edit_first_AC_5(client, db_session, reader):
    # Arrange (AC-5)
    headers = _register(client)
    state = _drifted_week(client, db_session, reader, headers)

    # Act
    response = client.get(f"/weeks/{_week(0)}/pdf", headers=headers)

    # Assert — exactly the copy, then the edit; no song key was asked for
    assert response.status_code == 200, response.text
    assert reader.keys == [state["plain_key"], state["edited_key"]]


# --- AC-6 .. AC-10: PATCH /scores/{id} writes that week's copy only ----------


def test_renaming_a_week_should_strip_and_change_only_that_week_AC_6(client, db_session):
    # Arrange (AC-6)
    headers = _register(client)
    song = _upload(client, headers, "옛 제목")
    target = _place(client, headers, song["song_id"], _week(0))
    other = _place(client, headers, song["song_id"], _week(1))
    song_before = _song_state(db_session, song["song_id"])

    # Act
    response = client.patch(f"/scores/{target}", json={"title": "  새 제목  "}, headers=headers)

    # Assert — trimmed, on this week only
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "새 제목"
    listed = _scores(client, headers)
    assert listed[target]["title"] == "새 제목"
    assert listed[other]["title"] == "옛 제목"
    # Assert — the song row did not move
    db_session.expire_all()
    assert _song_state(db_session, song["song_id"]) == song_before


def test_renaming_a_week_to_another_songs_title_should_be_accepted_AC_7(client, db_session):
    # Arrange — two songs of the same church (AC-7)
    headers = _register(client)
    mine = _upload(client, headers, "가나다")
    theirs = _upload(client, headers, "라마바")
    target = _place(client, headers, mine["song_id"], _week(0))
    neighbour = _place(client, headers, theirs["song_id"], _week(0))
    before = {
        song_id: _song_state(db_session, song_id) for song_id in (mine["song_id"], theirs["song_id"])
    }

    # Act
    response = client.patch(f"/scores/{target}", json={"title": "라마바"}, headers=headers)

    # Assert — accepted rather than 409, and only the week moved
    assert response.status_code == 200, response.text
    listed = _scores(client, headers)
    assert listed[target]["title"] == "라마바"
    assert listed[neighbour]["title"] == "라마바"
    assert listed[target]["song_id"] == mine["song_id"]
    db_session.expire_all()
    for song_id, state in before.items():
        assert _song_state(db_session, song_id) == state
    assert db_session.query(Song).count() == 2


def test_replacing_a_weeks_file_should_change_only_that_week_AC_8(client, db_session):
    # Arrange — both weeks edited, so a stray clear on the other one would show (AC-8)
    headers = _register(client)
    song = _upload(client, headers, "파일 바꿀 곡")
    target = _place(client, headers, song["song_id"], _week(0))
    other = _place(client, headers, song["song_id"], _week(1))
    _save_edit(client, headers, target)
    _save_edit(client, headers, other)
    other_before = _usage_state(db_session, other)
    song_before = _song_state(db_session, song["song_id"])
    key = _sign_week_file(client, headers, target)

    # Act
    response = client.patch(f"/scores/{target}", json={"file_uri": key}, headers=headers)

    # Assert — the response is the new copy
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file_uri"] == key
    assert key in unquote(body["download_url"])
    # Assert — the row took the key and dropped its edit
    db_session.expire_all()
    row = db_session.get(Score, target)
    assert row.file_uri == key
    assert row.file_url.startswith("http")
    assert row.file_url.endswith(key)
    assert (row.edited_file_uri, row.edit_doc, row.edit_source_uri) == (None, None, None)
    assert row.title == "파일 바꿀 곡"
    # Assert — the other week and the song did not move
    assert _usage_state(db_session, other) == other_before
    assert _song_state(db_session, song["song_id"]) == song_before


def test_a_foreign_key_with_a_title_should_400_and_change_nothing_AC_9(client, db_session):
    # Arrange — the title is valid on its own; the key check must run first (AC-9)
    other = _register(client, OTHER_CHURCH)
    other_church = _church_id(client, other)
    headers = _register(client)
    song = _upload(client, headers, "원래 제목")
    target = _place(client, headers, song["song_id"], _week(0))
    usage_before = _usage_state(db_session, target)
    song_before = _song_state(db_session, song["song_id"])

    # Act
    response = client.patch(
        f"/scores/{target}",
        json={"title": "새 제목", "file_uri": f"scores/{other_church}/x.png"},
        headers=headers,
    )

    # Assert — refused, and nothing was assigned even in memory
    assert response.status_code == 400, response.text
    assert _usage_state(db_session, target) == usage_before
    assert _song_state(db_session, song["song_id"]) == song_before
    assert _scores(client, headers)[target]["title"] == "원래 제목"


def test_renaming_an_edited_week_should_answer_with_its_edit_AC_10(client):
    # Arrange (AC-10)
    headers = _register(client)
    song = _upload(client, headers, "편집한 곡")
    target = _place(client, headers, song["song_id"], _week(0))
    edited_key = _save_edit(client, headers, target)

    # Act
    response = client.patch(f"/scores/{target}", json={"title": "고친 제목"}, headers=headers)

    # Assert — the PATCH answer follows the same rule as the reads
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "고친 제목"
    assert body["file_uri"] == song["key"]
    assert edited_key in unquote(body["download_url"])


# --- AC-11 / AC-12: the editor opens and records the week's copy -------------


def test_the_editor_should_open_on_the_weeks_copy_AC_11(client, db_session):
    # Arrange — never edited, then the song row drifted (AC-11)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song = _upload(client, headers, "편집기 곡")
    target = _place(client, headers, song["song_id"], _week(0))
    drift_key = f"scores/{church_id}/drifted.png"
    _drift_song(db_session, song["song_id"], key=drift_key)

    # Act
    response = client.get(f"/scores/{target}/edit", headers=headers)

    # Assert
    assert response.status_code == 200, response.text
    source = unquote(response.json()["source_image_url"])
    assert song["key"] in source
    assert drift_key not in source


def test_saving_an_edit_should_record_the_weeks_copy_as_its_source_AC_12(client, db_session):
    # Arrange — the song row drifted before the edit was saved (AC-12)
    headers = _register(client)
    church_id = _church_id(client, headers)
    song = _upload(client, headers, "기록할 곡")
    target = _place(client, headers, song["song_id"], _week(0))
    drift_key = f"scores/{church_id}/drifted.png"
    _drift_song(db_session, song["song_id"], key=drift_key)

    # Act
    _save_edit(client, headers, target)

    # Assert
    db_session.expire_all()
    row = db_session.get(Score, target)
    assert row.edit_source_uri == song["key"]
    assert row.edit_source_uri == row.file_uri
    assert row.edit_source_uri != drift_key
    reopened = unquote(client.get(f"/scores/{target}/edit", headers=headers).json()["source_image_url"])
    assert song["key"] in reopened
    assert drift_key not in reopened


# --- AC-13: a library file swap leaves every read of a placed week alone -----


def test_a_library_file_swap_should_not_change_a_placed_weeks_reads_AC_13(client, reader):
    # Arrange (AC-13)
    headers = _register(client)
    song = _upload(client, headers, "교체할 곡")
    target = _place(client, headers, song["song_id"], _week(0))
    signed = client.post(
        f"/songs/{song['song_id']}/file",
        json={"filename": "rescan.png", "content_type": "image/png"},
        headers=headers,
    )
    assert signed.status_code == 200, signed.text
    new_key = signed.json()["s3_key"]
    reader.serve(song["key"], _png((30, 175, 60)))
    reader.serve(new_key, _png((40, 60, 220)))

    # Act
    swapped = client.patch(f"/songs/{song['song_id']}", json={"file_uri": new_key}, headers=headers)
    assert swapped.status_code == 200, swapped.text

    # Assert — GET /scores
    item = _scores(client, headers)[target]
    assert item["file_uri"] == song["key"]
    assert song["key"] in unquote(item["download_url"])
    assert new_key not in unquote(item["download_url"])
    # Assert — the conti
    image_url = unquote(_conti(client, headers, _week(0))[target]["image_url"])
    assert song["key"] in image_url
    assert new_key not in image_url
    # Assert — the PDF
    pdf = client.get(f"/weeks/{_week(0)}/pdf", headers=headers)
    assert pdf.status_code == 200, pdf.text
    assert reader.keys == [song["key"]]


# --- AC-14: healing a missing file heals the weeks that pointed at it --------


def test_healing_a_missing_file_should_move_the_weeks_that_held_the_old_key_AC_14(client, db_session):
    # Arrange — two weeks; one swapped to its own key, the other edited (AC-14)
    headers = _register(client)
    first = _upload(client, headers, "은혜")
    healed = _place(client, headers, first["song_id"], _week(0))
    swapped = _place(client, headers, first["song_id"], _week(1))
    edited_key = _save_edit(client, headers, healed)
    own_key = _sign_week_file(client, headers, swapped)
    patched = client.patch(f"/scores/{swapped}", json={"file_uri": own_key}, headers=headers)
    assert patched.status_code == 200, patched.text
    missing = {first["key"]}
    app.dependency_overrides[get_object_probe] = lambda: lambda key: key not in missing

    # Act — the same title again, as the library does when a PUT never arrived
    response = client.post(
        "/songs",
        json={"title": "은혜", "filename": "score.png", "content_type": "image/png"},
        headers=headers,
    )

    # Assert — the song and the week that held the old key now hold the new one
    assert response.status_code == 201, response.text
    new_key = response.json()["s3_key"]
    assert response.json()["song_id"] == first["song_id"]
    assert new_key != first["key"]
    db_session.expire_all()
    song = db_session.get(Song, first["song_id"])
    assert song.file_uri == new_key
    assert song.file_url.endswith(new_key)
    row = db_session.get(Score, healed)
    assert row.file_uri == new_key
    assert row.file_url.startswith("http")
    assert row.file_url.endswith(new_key)
    # Assert — its edit is left exactly as it was
    assert (row.edited_file_uri, row.edit_doc, row.edit_source_uri) == (
        edited_key,
        EDIT_DOC,
        first["key"],
    )
    # Assert — the week with its own key is not touched
    other = db_session.get(Score, swapped)
    assert other.file_uri == own_key
    assert other.file_url.endswith(own_key)
    assert _scores(client, headers)[swapped]["file_uri"] == own_key


def test_healing_should_report_the_rows_it_moved_and_skip_a_song_with_no_key_AC_14(db_session, client):
    # Arrange — called directly: the route never hands it a keyless song (AC-14)
    from app.services.song import heal_song_file

    headers = _register(client)
    church_id = _church_id(client, headers)
    first = _upload(client, headers, "직접 치유")
    for n in range(2):
        _place(client, headers, first["song_id"], _week(n))
    keyless = _upload(client, headers, "키 없는 곡")
    keyless_week = _place(client, headers, keyless["song_id"], _week(0))
    db_session.get(Song, keyless["song_id"]).file_uri = None
    db_session.commit()
    new_key = f"scores/{church_id}/healed.png"

    # Act
    moved = heal_song_file(
        db_session,
        db_session.get(Song, first["song_id"]),
        file_url=f"https://example.invalid/{new_key}",
        file_uri=new_key,
    )
    skipped = heal_song_file(
        db_session,
        db_session.get(Song, keyless["song_id"]),
        file_url=f"https://example.invalid/{new_key}",
        file_uri=new_key,
    )

    # Assert
    assert moved == 2
    assert skipped == 0
    assert db_session.get(Score, keyless_week).file_uri == keyless["key"]


# --- AC-15: the tablet contract survives the change of source ----------------


def test_get_scores_should_keep_its_keys_and_order_while_serving_copies_AC_15(client, monkeypatch):
    # Arrange — three placements in order, then a library rename and a week rename (AC-15)
    headers = _register(client)
    serve_anonymous_scores(monkeypatch, client, headers)
    songs = [_upload(client, headers, title) for title in ("하나", "둘", "셋")]
    ids = [
        _place(client, headers, songs[0]["song_id"], _week(0)),
        _place(client, headers, songs[1]["song_id"], _week(0)),
        _place(client, headers, songs[2]["song_id"], _week(1)),
    ]
    renamed = client.patch(f"/songs/{songs[0]['song_id']}", json={"title": "보관함에서 고침"}, headers=headers)
    assert renamed.status_code == 200, renamed.text
    patched = client.patch(f"/scores/{ids[1]}", json={"title": "주차에서 고침"}, headers=headers)
    assert patched.status_code == 200, patched.text

    # Act — anonymous, exactly as the tablets call it
    response = client.get("/scores")

    # Assert — same keys, same order, values from each week's copy
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["id"] for item in items] == ids
    for item in items:
        assert set(item.keys()) == CONTRACT_KEYS | {"song_id"}, item.keys()
    assert [item["title"] for item in items] == ["하나", "주차에서 고침", "셋"]
    assert [item["song_id"] for item in items] == [song["song_id"] for song in songs]
