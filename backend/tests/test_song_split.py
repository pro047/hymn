"""Pins the song/usage split (DESIGN.md §7, cases 1-9a).

A `Song` is now the canonical title+file a church sings; a `Score` row is one
week's use of it. The properties fixed here are the ones the design bought:

- Reuse is the default and it never touches the song's file (D5). The failure
  this guards is not cosmetic: with 44% of weekly uploads hitting an existing
  title, a same-titled upload that updated the file would rewrite every past
  week about twice a week.
- A PATCH is the only way to change the file/title, and it changes every week
  (D3/D8) — that is the "reupload fixes only one week" bug this split closes.
- GET /scores keeps its Flutter contract: row-per-usage, created_at ascending,
  the original 8 keys, plus song_id and nothing else removed (D7).
"""

from datetime import date, timedelta

from app.models import Score, SetItem, Song


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()


def _week(n: int) -> str:
    """The n-th Sunday from this week. Future weeks, because reject_past_week
    refuses anything before this week's Sunday."""
    return (THIS_WEEK + timedelta(days=7 * n)).isoformat()


SIGNUP = {
    "name": "leader",
    "email": "leader@example.com",
    "password": "Password1",
    "church": "Split Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

OTHER_CHURCH = {**SIGNUP, "email": "other@example.com", "church": "Other Split Church"}


def _register(client, payload: dict = SIGNUP) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def _post_score(client, headers, *, title, week, filename="score.png", expect=200):
    response = client.post(
        "/scores",
        json={
            "title": title,
            "week_of": week,
            "storage_type": "s3",
            "filename": filename,
            "content_type": "image/png",
        },
        headers=headers,
    )
    assert response.status_code == expect, response.text
    return response


def _upload_saved(client, headers, *, title, filename="library.png", expect=201):
    response = client.post(
        "/me/saved-scores/upload",
        json={"title": title, "filename": filename, "content_type": "image/png"},
        headers=headers,
    )
    assert response.status_code == expect, response.text
    return response


def _songs(db_session) -> list[Song]:
    return db_session.query(Song).all()


# --- case 1 / 2-b: same title, different week = reuse ------------------------


def test_same_title_in_a_second_week_should_reuse_the_song(client, db_session):
    # Arrange
    headers = _register(client)

    # Act
    first = _post_score(client, headers, title="주 은혜임을", week=_week(0)).json()
    second = _post_score(
        client, headers, title="주 은혜임을", week=_week(1), filename="other.png"
    ).json()

    # Assert — one song, two usages, and the reuse is announced
    assert first["reused_song"] is False
    assert first["upload_url"]
    assert second["reused_song"] is True
    assert second["upload_url"] is None
    songs = _songs(db_session)
    assert len(songs) == 1
    assert db_session.query(Score).count() == 2
    listed = client.get("/scores").json()
    assert len(listed) == 2
    assert listed[0]["song_id"] == listed[1]["song_id"] == songs[0].id


def test_a_reused_create_should_point_at_the_songs_existing_file(client, db_session):
    """The candidate key minted for the second call was never uploaded to, so
    answering with it would hand the client a download_url that 404s."""
    # Arrange
    headers = _register(client)
    first = _post_score(client, headers, title="주 은혜임을", week=_week(0)).json()

    # Act
    second = _post_score(
        client, headers, title="주 은혜임을", week=_week(1), filename="other.png"
    ).json()

    # Assert — response and usage snapshot both carry the song's real file
    assert second["s3_key"] == first["s3_key"]
    assert first["s3_key"] in (second["download_url"] or "")
    snapshot = db_session.get(Score, second["score_id"])
    assert snapshot.file_uri == first["s3_key"]


# --- case 2: reuse must not update the file (the core of D5) -----------------


def test_reusing_a_song_should_not_replace_its_file(client, db_session):
    """If this breaks, the accidental-overwrite path is back: a same-titled
    upload with a different file would rewrite what every past week shows."""
    # Arrange
    headers = _register(client)
    first = _post_score(client, headers, title="주만 바라볼찌라", week=_week(0)).json()

    # Act
    _post_score(client, headers, title="주만 바라볼찌라", week=_week(1), filename="v2.jpg")

    # Assert
    song = _songs(db_session)[0]
    assert song.file_uri == first["s3_key"]
    assert song.file_url.endswith(first["s3_key"])


# --- case 2-a: same song, same week = 409 ------------------------------------


def test_the_same_song_in_the_same_week_should_return_409(client, db_session):
    # Arrange
    headers = _register(client)
    _post_score(client, headers, title="은혜", week=_week(0))

    # Act
    response = _post_score(client, headers, title="은혜", week=_week(0), expect=409)

    # Assert — refused in Korean, and nothing was written
    assert "이미 그 주차에" in response.text
    assert db_session.query(Score).count() == 1
    assert len(_songs(db_session)) == 1


# --- case 3: file replacement propagates to every week (D3) ------------------


def test_replacing_the_file_should_show_on_every_week(client, db_session):
    # Arrange
    headers = _register(client)
    usage1 = _post_score(client, headers, title="은혜", week=_week(0)).json()["score_id"]
    usage2 = _post_score(client, headers, title="은혜", week=_week(1)).json()["score_id"]
    church_id = db_session.get(Score, usage1).church_id
    new_key = f"scores/{church_id}/replacement.png"
    snapshot_before = db_session.get(Score, usage2).file_uri

    # Act
    patched = client.patch(f"/scores/{usage1}", json={"file_uri": new_key}, headers=headers)

    # Assert — both weeks now serve the new file
    assert patched.status_code == 200, patched.text
    listed = {item["id"]: item for item in client.get("/scores").json()}
    assert listed[usage1]["file_uri"] == new_key
    assert listed[usage2]["file_uri"] == new_key
    assert listed[usage2]["file_url"].startswith("http")
    assert listed[usage2]["file_url"].endswith(new_key)
    assert new_key in listed[usage2]["download_url"]
    # The other week's *snapshot* stays what was actually filed then: the
    # canonical value moved to songs, the history did not get rewritten.
    db_session.expire_all()
    assert db_session.get(Score, usage2).file_uri == snapshot_before


# --- case 4: rename propagates, collision is 409 (D8) ------------------------


def test_renaming_should_change_the_title_of_every_week(client):
    # Arrange
    headers = _register(client)
    usage1 = _post_score(client, headers, title="옛 제목", week=_week(0)).json()["score_id"]
    _post_score(client, headers, title="옛 제목", week=_week(1))

    # Act
    patched = client.patch(f"/scores/{usage1}", json={"title": "새 제목"}, headers=headers)

    # Assert
    assert patched.status_code == 200, patched.text
    titles = [item["title"] for item in client.get("/scores").json()]
    assert titles == ["새 제목", "새 제목"]


def test_renaming_onto_an_existing_song_should_return_409(client):
    # Arrange
    headers = _register(client)
    usage = _post_score(client, headers, title="가나다", week=_week(0)).json()["score_id"]
    _post_score(client, headers, title="라마바", week=_week(0))

    # Act
    response = client.patch(f"/scores/{usage}", json={"title": "라마바"}, headers=headers)

    # Assert — refused in Korean, and the title did not move
    assert response.status_code == 409, response.text
    assert "같은 제목" in response.text
    titles = {item["id"]: item["title"] for item in client.get("/scores").json()}
    assert titles[usage] == "가나다"


def test_renaming_to_a_spacing_variant_of_itself_should_be_accepted(client, db_session):
    """Same normalized key, so there is no collision to refuse — the user is
    fixing the display spacing of their own song."""
    # Arrange
    headers = _register(client)
    usage = _post_score(client, headers, title="참아름다워라", week=_week(0)).json()["score_id"]

    # Act
    response = client.patch(f"/scores/{usage}", json={"title": "참 아름다워라"}, headers=headers)

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "참 아름다워라"
    assert len(_songs(db_session)) == 1


# --- case 5: the unique key is per church ------------------------------------


def test_the_same_title_in_another_church_should_make_its_own_song(client, db_session):
    # Arrange
    ours = _register(client)
    theirs = _register(client, OTHER_CHURCH)

    # Act
    mine = _post_score(client, ours, title="은혜", week=_week(0)).json()
    other = _post_score(client, theirs, title="은혜", week=_week(0)).json()

    # Assert — no cross-church reuse, and no cross-church 409 either
    assert mine["reused_song"] is False
    assert other["reused_song"] is False
    assert len(_songs(db_session)) == 2


# --- case 6: DELETE removes the usage, not the song --------------------------


def test_deleting_one_usage_should_keep_the_song_and_the_other_weeks(client, db_session):
    # Arrange
    headers = _register(client)
    usage1 = _post_score(client, headers, title="은혜", week=_week(0)).json()["score_id"]
    usage2 = _post_score(client, headers, title="은혜", week=_week(1)).json()["score_id"]

    # Act
    response = client.delete(f"/scores/{usage1}", headers=headers)

    # Assert
    assert response.status_code == 204, response.text
    remaining = [item["id"] for item in client.get("/scores").json()]
    assert remaining == [usage2]
    assert len(_songs(db_session)) == 1


# --- case 6-a: attach_usage creates the missing SetItem (D11) ----------------


def _set_items_of(db_session, score_id: str) -> list[SetItem]:
    return db_session.query(SetItem).filter(SetItem.score_id == score_id).all()


def test_patching_a_week_onto_a_library_row_should_create_its_set_item(client, db_session):
    """The old PATCH did nothing when no SetItem existed (`if items:`); the
    unified attach_usage inserts one, and that change is deliberate — a library
    row moved into a week must end up in that week's set either way."""
    # Arrange — a library upload has week_of NULL and no SetItem
    headers = _register(client)
    score_id = _upload_saved(client, headers, title="보관곡").json()["score_id"]
    assert _set_items_of(db_session, score_id) == []

    # Act
    response = client.patch(
        f"/scores/{score_id}", json={"week_of": _week(0)}, headers=headers
    )

    # Assert
    assert response.status_code == 200, response.text
    items = _set_items_of(db_session, score_id)
    assert len(items) == 1
    assert items[0].week_date.isoformat() == _week(0)


def test_patch_and_apply_should_file_a_library_row_the_same_way(client, db_session):
    """D11's point: the result must not depend on which door the row came
    through. Same fixture, other door, same outcome as the test above."""
    # Arrange
    headers = _register(client)
    score_id = _upload_saved(client, headers, title="보관곡 둘").json()["score_id"]

    # Act
    response = client.post(
        f"/me/saved-scores/{score_id}/apply", json={"week_of": _week(0)}, headers=headers
    )

    # Assert — one SetItem in the same week, exactly like the PATCH door
    assert response.status_code == 200, response.text
    items = _set_items_of(db_session, score_id)
    assert len(items) == 1
    assert items[0].week_date.isoformat() == _week(0)


# --- case 7: the GET /scores contract ----------------------------------------

CONTRACT_KEYS = {
    "id",
    "church_id",
    "week_of",
    "title",
    "file_url",
    "file_uri",
    "download_url",
    "created_at",
}


def test_get_scores_should_keep_the_flutter_contract(client):
    # Arrange — three usages in creation order, plus one library row
    headers = _register(client)
    ids = [
        _post_score(client, headers, title=f"곡{i}", week=_week(i)).json()["score_id"]
        for i in range(3)
    ]
    library_id = _upload_saved(client, headers, title="비공개 보관곡").json()["score_id"]

    # Act — anonymous, exactly as the tablets call it
    response = client.get("/scores")

    # Assert
    assert response.status_code == 200, response.text
    items = response.json()
    for item in items:
        assert set(item.keys()) >= CONTRACT_KEYS, item.keys()
        assert item["song_id"] is not None
    # created_at ascending == creation order; a join must not reshuffle it
    assert [item["id"] for item in items] == ids
    # week_of NULL rows are the personal library and stay out of the answer
    assert library_id not in {item["id"] for item in items}


def test_get_one_score_should_serve_the_songs_file_not_the_snapshot(client, db_session):
    """GET /scores/{id} builds its answer separately from the list route, so
    the list serving canonical values does not prove the single route does.
    After a file replacement, the *other* week's snapshot still holds the old
    key — only reading through the song can answer with the new one."""
    # Arrange
    headers = _register(client)
    usage1 = _post_score(client, headers, title="은혜", week=_week(0)).json()["score_id"]
    usage2 = _post_score(client, headers, title="은혜", week=_week(1)).json()["score_id"]
    church_id = db_session.get(Score, usage1).church_id
    new_key = f"scores/{church_id}/replacement.png"
    patched = client.patch(f"/scores/{usage1}", json={"file_uri": new_key}, headers=headers)
    assert patched.status_code == 200, patched.text

    # Act
    response = client.get(f"/scores/{usage2}", headers=headers)

    # Assert — same key set as the list, and the song's file, not the snapshot
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body.keys()) >= CONTRACT_KEYS, body.keys()
    assert body["song_id"] is not None
    assert body["file_uri"] == new_key
    assert body["file_url"].endswith(new_key)


# --- case 8 / 8-a: the saved-scores path -------------------------------------


def test_a_saved_score_upload_should_carry_a_song_and_apply_should_publish_it(
    client, db_session
):
    # Arrange
    headers = _register(client)
    body = _upload_saved(client, headers, title="보관곡").json()
    score = db_session.get(Score, body["score_id"])
    assert score.song_id is not None

    # Act
    applied = client.post(
        f"/me/saved-scores/{body['score_id']}/apply",
        json={"week_of": _week(0)},
        headers=headers,
    )

    # Assert
    assert applied.status_code == 200, applied.text
    listed = {item["id"]: item for item in client.get("/scores").json()}
    assert body["score_id"] in listed
    assert listed[body["score_id"]]["song_id"] == score.song_id


def test_reuploading_a_saved_score_should_return_409(client, db_session):
    """D10: unlike POST /scores, the library answers a duplicate with 409 —
    its response schema has no room for a reused_song signal and issuing a
    presign anyway is what filled the bucket with orphans."""
    # Arrange
    headers = _register(client)
    first = _upload_saved(client, headers, title="보관곡").json()

    # Assert — the success schema was not widened to carry the web's signal
    assert "reused_song" not in first

    # Act
    response = _upload_saved(client, headers, title="보관곡", expect=409)

    # Assert
    assert "이미 등록된 곡" in response.text
    assert len(_songs(db_session)) == 1


def test_the_library_should_follow_the_song_after_a_rename_or_file_swap(client, db_session):
    """The library lists what the user would file *next*, so it reads the song —
    unlike the per-week snapshots that test_replacing_the_file_should_show_on_
    every_week deliberately freezes as history. Reading score.title/file_uri
    here left the two tabs disagreeing after a PATCH on any other week, and the
    superseded S3 key still resolves, so nothing surfaced the drift."""
    # Arrange — one saved row, plus a separate week's usage of the same song
    headers = _register(client)
    library_id = _upload_saved(client, headers, title="보관곡").json()["score_id"]
    usage_id = _post_score(client, headers, title="보관곡", week=_week(0)).json()["score_id"]
    church_id = db_session.get(Score, usage_id).church_id
    new_key = f"scores/{church_id}/renamed.png"

    # Act — patch the *other* week; the saved row itself is never touched
    patched = client.patch(
        f"/scores/{usage_id}",
        json={"title": "새 보관곡", "file_uri": new_key},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    # Assert
    listed = client.get("/me/saved-scores", headers=headers)
    assert listed.status_code == 200, listed.text
    items = {item["score_id"]: item for item in listed.json()}
    assert items[library_id]["title"] == "새 보관곡"
    assert items[library_id]["file_uri"] == new_key
    assert items[library_id]["file_url"].endswith(new_key)
    assert new_key in items[library_id]["download_url"]


# --- case 9 / 9-a: title normalization (D4) ----------------------------------


def test_spacing_and_case_variants_should_all_be_the_same_song(client, db_session):
    # Arrange
    headers = _register(client)
    variants = [
        "참 아름다워라",
        " 참 아름다워라 ",
        "참아름다워라",
        "참  아름다워라",
    ]

    # Act — each in its own week so only the title decides reuse
    responses = [
        _post_score(client, headers, title=title, week=_week(i)).json()
        for i, title in enumerate(variants)
    ]

    # Assert — one song, and the display title is the first registration's own
    assert [r["reused_song"] for r in responses] == [False, True, True, True]
    assert len(_songs(db_session)) == 1
    titles = {item["title"] for item in client.get("/scores").json()}
    assert titles == {"참 아름다워라"}


def test_title_case_should_not_split_a_song(client, db_session):
    # Arrange
    headers = _register(client)
    _post_score(client, headers, title="Amazing Grace", week=_week(0))

    # Act
    second = _post_score(client, headers, title="amazing grace", week=_week(1)).json()

    # Assert
    assert second["reused_song"] is True
    assert len(_songs(db_session)) == 1
    assert {item["title"] for item in client.get("/scores").json()} == {"Amazing Grace"}


def test_fullwidth_space_and_nbsp_should_normalize_too(client, db_session):
    """Catches an implementation that strips ' ' instead of \\s: U+3000 comes
    in from Korean IMEs and NBSP from pasted text, and both are real input.
    Built with chr() because both characters render like a plain space, and a
    plain space here would make this test a silent no-op."""
    # Arrange
    fullwidth_space = chr(0x3000)
    nbsp = chr(0x00A0)
    assert fullwidth_space != " " and nbsp != " "
    headers = _register(client)
    _post_score(client, headers, title="참 아름다워라", week=_week(0))

    # Act
    with_fullwidth = _post_score(
        client, headers, title="참" + fullwidth_space + "아름다워라", week=_week(1)
    ).json()
    with_nbsp = _post_score(
        client, headers, title="참" + nbsp + "아름다워라", week=_week(2)
    ).json()

    # Assert
    assert with_fullwidth["reused_song"] is True
    assert with_nbsp["reused_song"] is True
    assert len(_songs(db_session)) == 1
