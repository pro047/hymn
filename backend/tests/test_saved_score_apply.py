"""What applying a saved score does to the week it came from.

A saved score points at one usage row (a Score), and apply files that row under
the chosen week. The library's point is to reuse a song across Sundays, so the
week the row was already on must keep its song.
"""

from app.models import Score
from test_song_split import _post_score, _register, _week


def _conti_titles(client, headers, week: str) -> list[str]:
    response = client.get(f"/weeks/{week}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for page in response.json()["pages"] for item in page]


def test_applying_a_saved_score_should_keep_it_in_the_week_it_came_from(client):
    # Arrange — a song used this Sunday, saved to the library
    headers = _register(client)
    score_id = _post_score(client, headers, title="보관 재사용곡", week=_week(0)).json()["score_id"]
    saved = client.post(f"/me/saved-scores/{score_id}", headers=headers)
    assert saved.status_code == 204, saved.text

    # Act — reuse it next Sunday
    applied = client.post(
        f"/me/saved-scores/{score_id}/apply", json={"week_of": _week(1)}, headers=headers
    )

    # Assert
    assert applied.status_code == 200, applied.text
    assert _conti_titles(client, headers, _week(1)) == ["보관 재사용곡"]
    assert _conti_titles(client, headers, _week(0)) == ["보관 재사용곡"]


def _save(client, headers, score_id: str) -> None:
    response = client.post(f"/me/saved-scores/{score_id}", headers=headers)
    assert response.status_code == 204, response.text


def _apply(client, headers, score_id: str, week: str):
    return client.post(
        f"/me/saved-scores/{score_id}/apply", json={"week_of": week}, headers=headers
    )


def test_applying_a_saved_score_should_file_a_new_usage_of_the_same_song(client, db_session):
    # Arrange
    headers = _register(client)
    score_id = _post_score(client, headers, title="새 사용곡", week=_week(0)).json()["score_id"]
    _save(client, headers, score_id)

    # Act
    assert _apply(client, headers, score_id, _week(1)).status_code == 200

    # Assert — two usages of one song, the original still on its week
    original = db_session.get(Score, score_id)
    usages = db_session.query(Score).filter(Score.song_id == original.song_id).all()
    assert sorted(u.week_of.isoformat() for u in usages) == [_week(0), _week(1)]
    assert original.week_of.isoformat() == _week(0)


def test_applying_to_a_week_that_already_has_the_song_should_return_409(client):
    # Arrange
    headers = _register(client)
    score_id = _post_score(client, headers, title="중복곡", week=_week(0)).json()["score_id"]
    _save(client, headers, score_id)
    assert _apply(client, headers, score_id, _week(1)).status_code == 200

    # Act — the same week again, and the week it came from
    again = _apply(client, headers, score_id, _week(1))
    home = _apply(client, headers, score_id, _week(0))

    # Assert
    assert again.status_code == 409, again.text
    assert home.status_code == 409, home.text
    assert _conti_titles(client, headers, _week(1)) == ["중복곡"]
    assert _conti_titles(client, headers, _week(0)) == ["중복곡"]


def test_applying_should_leave_the_edit_on_the_week_it_was_drawn_for(client, db_session):
    # Arrange — this Sunday's usage carries an edit
    headers = _register(client)
    score_id = _post_score(client, headers, title="편집곡", week=_week(0)).json()["score_id"]
    original = db_session.get(Score, score_id)
    original.edited_file_uri = f"scores/{original.church_id}/edits/drawn.png"
    original.edit_doc = {"objects": []}
    original.edit_source_uri = original.file_uri
    db_session.commit()
    _save(client, headers, score_id)

    # Act
    assert _apply(client, headers, score_id, _week(1)).status_code == 200

    # Assert — the edit stays where it was drawn; the new week starts clean
    db_session.refresh(original)
    assert original.edited_file_uri is not None
    new = (
        db_session.query(Score)
        .filter(Score.song_id == original.song_id, Score.id != score_id)
        .one()
    )
    assert (new.edited_file_uri, new.edit_doc, new.edit_source_uri) == (None, None, None)


def test_applying_should_count_the_use_on_the_saved_entry(client):
    # Arrange
    headers = _register(client)
    score_id = _post_score(client, headers, title="카운트곡", week=_week(0)).json()["score_id"]
    _save(client, headers, score_id)

    # Act
    first = _apply(client, headers, score_id, _week(1))
    second = _apply(client, headers, score_id, _week(2))

    # Assert — still one saved entry, pointing at the original usage
    assert (first.json()["use_count"], second.json()["use_count"]) == (1, 2)
    listed = client.get("/me/saved-scores", headers=headers).json()
    assert [(item["score_id"], item["use_count"]) for item in listed] == [(score_id, 2)]
