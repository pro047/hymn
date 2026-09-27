"""The library holds songs, not weekly usages.

An entry is a song the user wants to reach again, so it has to survive any one
Sunday being taken off, answer "when was this last sung" from every Sunday the
church used it on, and file a *new* usage when it is applied -- the week the
song was already on keeps it.
"""

from app.models import SavedScore, Score
from test_song_split import OTHER_CHURCH, _post_score, _register, _upload_saved, _week


def _conti_titles(client, headers, week: str) -> list[str]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for page in response.json()["pages"] for item in page]


def _usage(client, headers, title: str, week: str) -> dict:
    return _post_score(client, headers, title=title, week=week).json()


def _song_of(db_session, score_id: str) -> str:
    return db_session.get(Score, score_id).song_id


def _save(client, headers, song_id: str, expect: int = 204):
    response = client.post(f"/me/saved-scores/{song_id}", headers=headers)
    assert response.status_code == expect, response.text
    return response


def _apply(client, headers, song_id: str, week: str):
    return client.post(
        f"/me/saved-scores/{song_id}/apply", json={"week_of": week}, headers=headers
    )


def _library(client, headers) -> list[dict]:
    response = client.get("/me/saved-scores", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_applying_a_saved_song_should_keep_it_in_the_week_it_came_from(client, db_session):
    # Arrange — a song used this Sunday, saved to the library
    headers = _register(client)
    song_id = _song_of(db_session, _usage(client, headers, "보관 재사용곡", _week(0))["score_id"])
    _save(client, headers, song_id)

    # Act — reuse it next Sunday
    applied = _apply(client, headers, song_id, _week(1))

    # Assert
    assert applied.status_code == 200, applied.text
    assert _conti_titles(client, headers, _week(1)) == ["보관 재사용곡"]
    assert _conti_titles(client, headers, _week(0)) == ["보관 재사용곡"]


def test_applying_to_a_week_that_already_has_the_song_should_return_409(client, db_session):
    # Arrange
    headers = _register(client)
    song_id = _song_of(db_session, _usage(client, headers, "중복곡", _week(0))["score_id"])
    _save(client, headers, song_id)

    # Act
    response = _apply(client, headers, song_id, _week(0))

    # Assert
    assert response.status_code == 409, response.text
    assert "이미 그 주차" in response.json()["detail"]
    assert _conti_titles(client, headers, _week(0)) == ["중복곡"]


def test_applying_should_leave_the_edit_on_the_week_it_was_drawn_for(client, db_session):
    # Arrange — this Sunday's usage carries an edit
    headers = _register(client)
    score_id = _usage(client, headers, "편집곡", _week(0))["score_id"]
    original = db_session.get(Score, score_id)
    original.edited_file_uri = f"scores/{original.church_id}/edits/drawn.png"
    original.edit_doc = {"objects": []}
    original.edit_source_uri = original.file_uri
    db_session.commit()
    _save(client, headers, original.song_id)

    # Act
    assert _apply(client, headers, original.song_id, _week(1)).status_code == 200

    # Assert — the edit stays where it was drawn; the new week starts clean
    db_session.refresh(original)
    assert original.edited_file_uri is not None
    new = (
        db_session.query(Score)
        .filter(Score.song_id == original.song_id, Score.id != score_id)
        .one()
    )
    assert (new.edited_file_uri, new.edit_doc, new.edit_source_uri) == (None, None, None)


def test_the_entry_should_survive_the_week_it_was_saved_from_being_deleted(client, db_session):
    # Arrange — saved from this Sunday, reused next Sunday
    headers = _register(client)
    score_id = _usage(client, headers, "남는곡", _week(0))["score_id"]
    song_id = _song_of(db_session, score_id)
    _save(client, headers, song_id)
    assert _apply(client, headers, song_id, _week(1)).status_code == 200

    # Act — this Sunday's usage is taken off
    deleted = client.delete(f"/scores/{score_id}", headers=headers)

    # Assert
    assert deleted.status_code in (200, 204), deleted.text
    assert [item["song_id"] for item in _library(client, headers)] == [song_id]


def test_the_entry_should_report_the_latest_week_and_how_many_weeks_used_it(client, db_session):
    # Arrange — used this Sunday by upload, then two more Sundays from the library
    headers = _register(client)
    song_id = _song_of(db_session, _usage(client, headers, "자주곡", _week(0))["score_id"])
    _save(client, headers, song_id)
    _apply(client, headers, song_id, _week(2))
    _apply(client, headers, song_id, _week(1))

    # Act
    [item] = _library(client, headers)

    # Assert — every Sunday counts, however it was filed
    assert item["use_count"] == 3
    assert item["last_week_of"] == _week(2)


def test_saving_a_second_week_of_the_same_song_should_not_add_an_entry(client, db_session):
    # Arrange — the same song on two Sundays
    headers = _register(client)
    song_id = _song_of(db_session, _usage(client, headers, "한곡", _week(0))["score_id"])
    _usage(client, headers, "한곡", _week(1))

    # Act — saved from both
    _save(client, headers, song_id)
    _save(client, headers, song_id)

    # Assert
    assert db_session.query(SavedScore).count() == 1


def test_saving_another_churchs_song_should_return_404(client, db_session):
    # Arrange
    other = _register(client, OTHER_CHURCH)
    foreign_song = _song_of(db_session, _usage(client, other, "남의곡", _week(0))["score_id"])
    headers = _register(client)

    # Act / Assert
    _save(client, headers, foreign_song, expect=404)


def test_uploading_to_the_library_should_not_file_a_usage(client, db_session):
    # Act
    headers = _register(client)
    body = _upload_saved(client, headers, title="보관 전용곡").json()

    # Assert — a song and an entry, no Sunday
    assert db_session.query(Score).count() == 0
    [item] = _library(client, headers)
    assert item["song_id"] == body["song_id"]
    assert (item["use_count"], item["last_week_of"]) == (0, None)


def test_the_frequent_sort_should_put_the_most_used_song_first(client, db_session):
    # Arrange — one song on one Sunday, another on two
    headers = _register(client)
    once = _song_of(db_session, _usage(client, headers, "한 번", _week(0))["score_id"])
    twice = _song_of(db_session, _usage(client, headers, "두 번", _week(0))["score_id"])
    _usage(client, headers, "두 번", _week(1))
    _save(client, headers, once)
    _save(client, headers, twice)

    # Act
    response = client.get("/me/saved-scores?sort=frequent", headers=headers)

    # Assert
    assert [item["song_id"] for item in response.json()] == [twice, once]


def test_a_weekless_legacy_usage_should_not_count_as_a_use(client, db_session):
    # Arrange — older library uploads filed a usage with no Sunday (dev has two)
    headers = _register(client)
    score_id = _usage(client, headers, "옛 보관곡", _week(0))["score_id"]
    legacy = db_session.get(Score, score_id)
    legacy.week_of = None
    db_session.commit()
    _save(client, headers, legacy.song_id)

    # Act
    [item] = _library(client, headers)

    # Assert
    assert (item["use_count"], item["last_week_of"]) == (0, None)
