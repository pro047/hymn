"""Pins the GET /weeks/{week_of}/pdf contract (DESIGN.md §9, criteria 13-27).

S3 is replaced through app.dependency_overrides[get_object_reader] — the same
seam conftest uses for get_session — so no test here opens a socket. Everything
else (the church, the songs, the set items) goes through the real routes and the
real test database.

Two habits worth keeping when extending this file:

- Each song is served a different flat colour, and the assertions read the
  colour back out of the rendered page. That fixes *which song landed in which
  slot*, which neither a page count nor a call-order assertion can do.
- The reader stub records every key it is handed, so "this key was never read"
  is assertable — that is the only way to test a gate that must refuse *before*
  the network call, not after it.
"""

import logging
import re
from datetime import date, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app.deps import get_object_reader
from app.main import app
from app.models import Score, SetItem, Song
from app.utils.s3 import ObjectNotReadable

PAGE_W, PAGE_H = 1754, 1240
MARGIN = 47
SLOT_W, SLOT_H = 812, 1146
LEFT_X, RIGHT_X = 47, 895

WHITE = (255, 255, 255)
RED = (220, 30, 30)
GREEN = (30, 175, 60)
BLUE = (40, 60, 220)
YELLOW = (230, 200, 40)
PURPLE = (140, 40, 170)
PALETTE = [RED, GREEN, BLUE, YELLOW, PURPLE]

JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"

# Not an image Pillow can open, and the exact shape production would hit: a
# score whose "file" is a PDF someone uploaded.
PDF_UPLOAD = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()


def _week(n: int) -> str:
    """The n-th Sunday from this one. Future only — reject_past_week refuses
    anything before this week's Sunday."""
    return (THIS_WEEK + timedelta(days=7 * n)).isoformat()


SIGNUP = {
    "name": "leader",
    "email": "leader@example.com",
    "password": "Password1",
    "church": "Conti Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}
OTHER_SIGNUP = {**SIGNUP, "email": "other@example.com", "church": "Other Conti Church"}


class RecordingReader:
    """The object reader a request gets instead of S3.

    Records keys in call order and can be told to fail one of them, which is
    what the 502 and the pre-read gate tests need.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, bytes] = {}
        self.failures: dict[str, Exception] = {}
        self.keys: list[str] = []

    def serve(self, key: str, payload: bytes) -> None:
        self.payloads[key] = payload

    def fail(self, key: str, error: Exception) -> None:
        self.failures[key] = error

    def __call__(self, key: str) -> bytes:
        self.keys.append(key)
        if key in self.failures:
            raise self.failures[key]
        return self.payloads[key]


@pytest.fixture()
def reader():
    stub = RecordingReader()
    app.dependency_overrides[get_object_reader] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_object_reader, None)


def _png(color: tuple[int, int, int], size: tuple[int, int] = (SLOT_W // 2, SLOT_H // 2)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _register(client, payload: dict = SIGNUP) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def _church_id(client, headers: dict) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["church_id"]


def _add_song(client, reader, headers: dict, *, title: str, week: str, color=RED) -> dict:
    """Files one song for a week and makes its object readable as `color`.

    Returns {"score_id", "key", "color"} — the key is what the reader will be
    asked for, so tests can assert on call order against it.
    """
    response = client.post(
        "/scores",
        json={
            "title": title,
            "week_of": week,
            "storage_type": "s3",
            "filename": "score.png",
            "content_type": "image/png",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    reader.serve(body["s3_key"], _png(color))
    return {"score_id": body["score_id"], "key": body["s3_key"], "color": color}


def _seed_week(client, reader, headers: dict, week: str, count: int) -> list[dict]:
    return [
        _add_song(client, reader, headers, title=f"곡{i}", week=week, color=PALETTE[i])
        for i in range(count)
    ]


def _get_pdf(client, headers: dict, week: str):
    return client.get(f"/weeks/{week}/pdf", headers=headers)


def _pdf_page_images(pdf: bytes) -> list[Image.Image]:
    """The rendered pages, in file order. Each RGB page is a raw JPEG stream;
    FF D9 inside one only ever means end-of-image because entropy-coded FF is
    byte-stuffed, so scanning for the markers is unambiguous."""
    pages = []
    start = pdf.find(JPEG_SOI)
    while start != -1:
        end = pdf.find(JPEG_EOI, start)
        assert end != -1, "JPEG stream without an EOI marker"
        page = Image.open(BytesIO(pdf[start : end + 2]))
        page.load()
        pages.append(page)
        start = pdf.find(JPEG_SOI, end + 2)
    return pages


def _declared_page_count(pdf: bytes) -> int:
    match = re.search(rb"/Count (\d+)\n", pdf)
    assert match is not None, "no page tree /Count in the PDF"
    return int(match.group(1))


def _slot_center(slot: int) -> tuple[int, int]:
    return (LEFT_X, RIGHT_X)[slot] + SLOT_W // 2, MARGIN + SLOT_H // 2


def _assert_color(page: Image.Image, xy: tuple[int, int], expected: tuple[int, int, int]) -> None:
    actual = page.convert("RGB").getpixel(xy)
    assert all(abs(a - e) <= 16 for a, e in zip(actual, expected, strict=True)), (
        f"at {xy}: got {actual}, expected ~{expected}"
    )


def _assert_song_order(pdf: bytes, songs: list[dict]) -> None:
    """Every song sits in the slot its position demands, left to right, two per
    page — read off the pixels, not off the call log."""
    pages = _pdf_page_images(pdf)
    assert len(pages) == (len(songs) + 1) // 2
    for index, song in enumerate(songs):
        _assert_color(pages[index // 2], _slot_center(index % 2), song["color"])


def _set_order_no(db_session, score_id: str, order_no: int) -> None:
    db_session.query(SetItem).filter(SetItem.score_id == score_id).update({"order_no": order_no})


def _set_created_at(db_session, score_id: str, when) -> None:
    db_session.query(Score).filter(Score.id == score_id).update({"created_at": when})


# --- criterion 13: authentication --------------------------------------------


def test_calling_without_a_token_should_return_401(client, reader):
    # Act
    response = client.get(f"/weeks/{_week(0)}/pdf")

    # Assert — the shared wording, not a route-local one
    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "로그인이 만료되었습니다. 다시 로그인해 주세요."
    assert reader.keys == []


def test_a_token_for_the_wrong_version_should_return_401(client, reader):
    """A password change retires every access token; this route must honour
    that like the rest, rather than only checking the signature."""
    # Arrange
    headers = _register(client)
    _add_song(client, reader, headers, title="곡", week=_week(0))
    changed = client.post(
        "/auth/password",
        json={"current_password": "Password1", "new_password": "Password2"},
        headers=headers,
    )
    assert changed.status_code == 204, changed.text

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 401, response.text
    assert reader.keys == []


# --- criterion 14: church scope ----------------------------------------------


def test_a_church_should_only_see_its_own_songs(client, reader):
    """Requirement 2. Week rows are shared across churches (there is no
    church_id on `weeks`), so the scope has to come from Score.church_id — a
    query that leaned on the week would hand church B all five songs."""
    # Arrange — both churches file into the same week
    church_a = _register(client)
    church_b = _register(client, OTHER_SIGNUP)
    ours = _seed_week(client, reader, church_a, _week(0), 3)
    theirs = [
        _add_song(client, reader, church_b, title="우리곡0", week=_week(0), color=YELLOW),
        _add_song(client, reader, church_b, title="우리곡1", week=_week(0), color=PURPLE),
    ]

    # Act
    response = _get_pdf(client, church_b, _week(0))

    # Assert — one page, church B's two songs, church A's keys never touched
    assert response.status_code == 200, response.text
    assert _declared_page_count(response.content) == 1
    assert reader.keys == [song["key"] for song in theirs]
    for song in ours:
        assert song["key"] not in reader.keys
    _assert_song_order(response.content, theirs)


# --- criterion 15: path validation -------------------------------------------


@pytest.mark.parametrize("week_of", ["abc", "2026-13-01", "2026-9-6", "1700000000", "2026-02-30"])
def test_a_date_that_is_not_yyyy_mm_dd_should_return_422(client, reader, week_of):
    """Authenticated on purpose: the auth dependency is solved before the path
    parameter is validated, so an anonymous call would answer 401 and prove
    nothing about the date."""
    # Arrange
    headers = _register(client)

    # Act
    response = client.get(f"/weeks/{week_of}/pdf", headers=headers)

    # Assert
    assert response.status_code == 422, response.text
    assert reader.keys == []


# --- criterion 16: empty week ------------------------------------------------


def test_a_week_with_no_songs_should_return_404(client, reader):
    # Arrange — a neighbouring week does have songs
    headers = _register(client)
    _seed_week(client, reader, headers, _week(0), 2)

    # Act
    response = _get_pdf(client, headers, _week(1))

    # Assert
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "그 주차에 등록된 곡이 없습니다."
    assert reader.keys == []


# --- criteria 17-18: the response --------------------------------------------


def test_the_response_should_be_a_pdf_attachment_named_for_the_week(client, reader):
    # Arrange
    headers = _register(client)
    _seed_week(client, reader, headers, _week(0), 2)

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="conti-{_week(0)}.pdf"'
    assert response.content.startswith(b"%PDF")
    assert response.content.endswith(b"%%EOF")


def test_five_songs_should_make_three_pages_with_one_song_on_the_last(client, reader):
    """Requirement 6. The page count alone would not catch a last page that
    repeated song four, so the right-hand slot is checked for bare canvas."""
    # Arrange
    headers = _register(client)
    songs = _seed_week(client, reader, headers, _week(0), 5)

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 200, response.text
    assert _declared_page_count(response.content) == 3
    _assert_song_order(response.content, songs)
    _assert_color(_pdf_page_images(response.content)[2], _slot_center(1), WHITE)


# --- criteria 19-21: ordering ------------------------------------------------


def test_songs_should_follow_order_no_ascending(client, reader, db_session):
    # Arrange — file them in one order, set the week's running order to another
    headers = _register(client)
    first, second, third = _seed_week(client, reader, headers, _week(0), 3)
    _set_order_no(db_session, first["score_id"], 3)
    _set_order_no(db_session, second["score_id"], 1)
    _set_order_no(db_session, third["score_id"], 2)

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — both the read order and the placement follow order_no
    assert response.status_code == 200, response.text
    expected = [second, third, first]
    assert reader.keys == [song["key"] for song in expected]
    _assert_song_order(response.content, expected)


def test_a_tie_in_order_no_should_be_broken_by_created_at(client, reader, db_session):
    """Criterion 20. created_at is a Python-side default, so two rows really can
    share a microsecond — but a tie must still resolve the same way twice, and
    it must resolve the way GET /scores already shows them."""
    # Arrange — same order_no, and the later-filed song is made the older row
    headers = _register(client)
    early, late = _seed_week(client, reader, headers, _week(0), 2)
    _set_order_no(db_session, early["score_id"], 1)
    _set_order_no(db_session, late["score_id"], 1)
    _set_created_at(db_session, early["score_id"], datetime(2026, 1, 2, 9, 0, 0))
    _set_created_at(db_session, late["score_id"], datetime(2026, 1, 1, 9, 0, 0))

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — the older created_at comes first, not the insertion order
    assert response.status_code == 200, response.text
    assert reader.keys == [late["key"], early["key"]]
    _assert_song_order(response.content, [late, early])


def test_a_song_with_no_set_item_should_come_last(client, reader, db_session):
    """NULLS LAST. A join instead of the correlated subquery would drop this
    song from the PDF entirely, which is the silent failure decision 4 refuses."""
    # Arrange — song 0 loses its set item, songs 1 and 2 keep order 2 and 3
    headers = _register(client)
    orphan, second, third = _seed_week(client, reader, headers, _week(0), 3)
    db_session.query(SetItem).filter(SetItem.score_id == orphan["score_id"]).delete()

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — still three songs, the unordered one at the back
    assert response.status_code == 200, response.text
    expected = [second, third, orphan]
    assert reader.keys == [song["key"] for song in expected]
    assert _declared_page_count(response.content) == 2
    _assert_song_order(response.content, expected)


def test_a_score_with_two_set_items_should_still_appear_once(client, reader, db_session):
    """attach_usage moves *every* one of a score's set items onto the new week,
    so two rows for one score in one week is reachable. A join would emit the
    song twice and push the page count up; the MIN() subquery must not."""
    # Arrange
    headers = _register(client)
    first, second = _seed_week(client, reader, headers, _week(0), 2)
    original = db_session.query(SetItem).filter(SetItem.score_id == first["score_id"]).one()
    db_session.add(
        SetItem(
            week_id=original.week_id,
            week_date=original.week_date,
            order_no=original.order_no + 10,
            score_id=first["score_id"],
        )
    )

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — two songs on one page, and the smaller order_no is the one used
    assert response.status_code == 200, response.text
    assert reader.keys == [first["key"], second["key"]]
    assert _declared_page_count(response.content) == 1
    _assert_song_order(response.content, [first, second])


# --- criterion 22: determinism -----------------------------------------------


def test_the_same_request_twice_should_return_the_same_bytes(client, reader):
    """Requirement 3. A CreationDate stamp would only differ across a second
    boundary, so the absence of the stamp is asserted too rather than trusting
    two calls that may land in the same second."""
    # Arrange
    headers = _register(client)
    _seed_week(client, reader, headers, _week(0), 3)

    # Act
    first = _get_pdf(client, headers, _week(0))
    second = _get_pdf(client, headers, _week(0))

    # Assert
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert b"/CreationDate" not in first.content
    assert b"/ModDate" not in first.content


# --- criteria 23-24: read failure --------------------------------------------


def test_a_read_failure_should_fail_the_whole_request_with_502(client, reader):
    """Decision 4: a song quietly dropped from the PDF leaves no trace inside
    the file, and the leader finds out at rehearsal. So no partial PDF."""
    # Arrange — the first song reads fine, the second does not
    headers = _register(client)
    good, bad = _seed_week(client, reader, headers, _week(0), 2)
    reader.fail(bad["key"], ObjectNotReadable(bad["key"]))

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — 502 naming the song, and nothing PDF-shaped comes back
    assert response.status_code == 502, response.text
    assert response.json()["detail"] == "악보 파일을 불러오지 못했습니다: 곡1"
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"%PDF")
    assert reader.keys == [good["key"], bad["key"]]


def test_a_read_failure_should_be_logged_at_warning_with_the_score_id(client, reader, caplog):
    """Criterion 24. INFO never reaches production logs — root sits at the
    WARNING uvicorn left it at — so at_level(WARNING) here makes an INFO call
    fail this test rather than pass it invisibly."""
    # Arrange
    headers = _register(client)
    (song,) = _seed_week(client, reader, headers, _week(0), 1)
    reader.fail(song["key"], ObjectNotReadable(song["key"]))

    # Act
    with caplog.at_level(logging.WARNING):
        response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 502, response.text
    warnings = [
        record
        for record in caplog.records
        if record.name == "app.services.conti" and record.levelno == logging.WARNING
    ]
    assert warnings, "the read failure left no WARNING behind"
    message = warnings[0].getMessage()
    assert song["score_id"] in message
    assert song["key"] in message
    # Decision 4: never the presigned URL, never the object bytes
    assert "http" not in message


# --- criterion 25: a file that is not an image -------------------------------


def test_a_file_that_is_not_an_image_should_return_409(client, reader):
    """Requirement 9. Judged on the bytes, not the extension or the stored
    content type — the client picks both of those when it PUTs."""
    # Arrange
    headers = _register(client)
    good, bad = _seed_week(client, reader, headers, _week(0), 2)
    reader.serve(bad["key"], PDF_UPLOAD)

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — 409, not 502: the fix is to replace the file, not to retry
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "이미지가 아닌 악보 파일이 있어 콘티를 만들 수 없습니다: 곡1"
    assert reader.keys == [good["key"], bad["key"]]


# --- criterion 26: the key gate, before the read -----------------------------


def test_a_song_with_no_file_uri_should_502_without_a_read(client, reader, db_session):
    # Arrange — the good song is first so "never read" is distinguishable from
    # "the loop never got there"
    headers = _register(client)
    good, broken = _seed_week(client, reader, headers, _week(0), 2)
    song_id = db_session.get(Score, broken["score_id"]).song_id
    db_session.query(Song).filter(Song.id == song_id).update({"file_uri": None})

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 502, response.text
    assert response.json()["detail"] == "악보 파일을 불러오지 못했습니다: 곡1"
    assert reader.keys == [good["key"]]


def test_a_key_outside_the_scores_prefix_should_502_without_a_read(client, reader, db_session):
    """Decision 5: the gate keeps a path that is not an uploaded score out of
    read_object, and refuses before the call so the object is never requested."""
    # Arrange
    headers = _register(client)
    off_bucket_key = "uploads/../../etc/passwd"
    good, broken = _seed_week(client, reader, headers, _week(0), 2)
    song_id = db_session.get(Score, broken["score_id"]).song_id
    db_session.query(Song).filter(Song.id == song_id).update({"file_uri": off_bucket_key})
    reader.serve(off_bucket_key, _png(PURPLE))

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — readable object, still refused, and never asked for
    assert response.status_code == 502, response.text
    assert reader.keys == [good["key"]]
    assert off_bucket_key not in reader.keys


def test_a_legacy_placeholder_key_should_still_render(client, reader, db_session):
    """Regression, measured 2026-09-06: 60 of the 85 production songs carry
    keys minted before ece1e92, whose literal placeholder segment makes them
    scores/.../{uuid}.{ext} rather than scores/{church_id}/. Requiring the
    church segment here would 502 on 27 of the 32 production weeks. Church
    scoping is the query's job (see the church-isolation test above); this
    gate must not reject a legacy key."""
    # Arrange
    headers = _register(client)
    legacy_key = "scores/.../7957df3e-1663-474a-b104-993dc738a311.png"
    good, legacy = _seed_week(client, reader, headers, _week(0), 2)
    song_id = db_session.get(Score, legacy["score_id"]).song_id
    db_session.query(Song).filter(Song.id == song_id).update({"file_uri": legacy_key})
    reader.serve(legacy_key, _png(PURPLE))

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — rendered, and the legacy object really was read
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    assert legacy_key in reader.keys
    assert good["key"] in reader.keys


# --- criterion 27: the shared contract this router must not disturb ----------

SCORES_CONTRACT_KEYS = {
    "id",
    "church_id",
    "week_of",
    "title",
    "file_url",
    "file_uri",
    "download_url",
    "created_at",
    "song_id",
}


def test_get_scores_should_keep_its_exact_key_set_and_ordering(client, reader):
    """Lives in this file because the verification step may only touch the two
    conti test files; test_song_split.py already checks the same route but with
    `>=`, so a key added to ScoreResponse would slip past it. The Flutter app
    parses this response — an added key is a contract change either way.
    """
    # Arrange — three usages, created in a known order
    headers = _register(client)
    songs = [
        _add_song(client, reader, headers, title=f"곡{i}", week=_week(i))
        for i in range(3)
    ]

    # Act — anonymous, exactly how the tablets call it
    response = client.get("/scores")

    # Assert
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["id"] for item in items] == [song["score_id"] for song in songs]
    for item in items:
        assert set(item.keys()) == SCORES_CONTRACT_KEYS, item.keys()


# --- code review 2026-09-06: five findings, fixed and pinned here -----------


def _rgba_png(color: tuple[int, int, int], size: tuple[int, int] = (SLOT_W // 2, SLOT_H // 2)) -> bytes:
    """A fully transparent PNG whose hidden RGB is black — the shape a
    transparent export takes when its background was never painted."""
    buffer = BytesIO()
    Image.new("RGBA", size, (*color, 0)).save(buffer, "PNG")
    return buffer.getvalue()


def test_a_transparent_png_should_flatten_onto_white_not_black(client, reader):
    """convert("RGB") on an RGBA image keeps the RGB under the transparent
    pixels — black for a typical export — so the song's half of the sheet
    would come out solid black with nothing flagging it. 7 of the 85
    production songs already carry an alpha channel (measured 2026-09-06)."""
    # Arrange
    headers = _register(client)
    song = _add_song(client, reader, headers, title="투명곡", week=_week(0))
    reader.serve(song["key"], _rgba_png((0, 0, 0)))

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert — the slot is white, not black
    assert response.status_code == 200, response.text
    page = _pdf_page_images(response.content)[0]
    _assert_color(page, _slot_center(0), (255, 255, 255))


def test_a_truncated_image_should_502_not_409(client, reader):
    """load() raises OSError on a valid image with incomplete bytes — an
    interrupted upload. 409 tells the leader their file is wrong and not to
    retry; the right answer is the retryable 502."""
    # Arrange
    headers = _register(client)
    song = _add_song(client, reader, headers, title="잘린곡", week=_week(0))
    whole = _png(RED)
    reader.serve(song["key"], whole[: len(whole) // 2])

    # Act
    response = _get_pdf(client, headers, _week(0))

    # Assert
    assert response.status_code == 502, response.text
    assert "잘린곡" in response.json()["detail"]


def test_an_object_over_the_size_cap_should_be_refused_before_its_body_is_read(monkeypatch):
    """presign_put signs a PUT with no size condition, so nothing upstream
    caps an object. The cap reads GetObject metadata and refuses before
    Body.read(), which is what keeps an oversized object out of a 2 GiB box."""
    # Arrange
    from app.utils import s3 as s3_module

    read_calls = []

    class _Body:
        def read(self):
            read_calls.append(1)
            return b"x" * 999

    class _Client:
        def get_object(self, **kwargs):
            return {"ContentLength": s3_module.MAX_OBJECT_BYTES + 1, "Body": _Body()}

    monkeypatch.setattr(s3_module, "s3_client", _Client())

    # Act & Assert — refused, and the body was never pulled
    with pytest.raises(s3_module.ObjectTooLarge):
        s3_module.get_object_bytes("scores/x/big.png")
    assert read_calls == []


def test_an_object_within_the_size_cap_should_be_read(monkeypatch):
    """The cap must not shave real data: production's largest score is
    1.20 MB (85 songs measured 2026-09-06) against a 20 MB limit."""
    # Arrange
    from app.utils import s3 as s3_module

    class _Body:
        def read(self):
            return b"payload"

    class _Client:
        def get_object(self, **kwargs):
            return {"ContentLength": 1_260_000, "Body": _Body()}

    monkeypatch.setattr(s3_module, "s3_client", _Client())

    # Act & Assert
    assert s3_module.get_object_bytes("scores/x/ok.png") == b"payload"
