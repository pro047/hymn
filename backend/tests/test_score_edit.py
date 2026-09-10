"""Pins the write side of a week's edited sheet.

b5d3e9a71f28 gave a week somewhere to hang an edited sheet and nothing that
could put one there, so `edited_file_uri` was NULL on every row and the column
was unreachable. These routes are what write it, and writing it is what makes
two things possible that were not before: a key arriving from the request, and
a picture that outlives the sheet it was drawn on.

Both are fixed here. The key goes through the same church gate every other
written key does, and the picture is cleared by the two events that invalidate
it — replacing the song's file, and moving the usage to another week.

The third property is the one that is easy to get backwards: the editor opens
the *song's* file, not the edited one. Reopening the edited sheet would put
every earlier marking on the canvas twice, once baked into the background and
once as the object that drew it.
"""

from datetime import date, timedelta

from app.models import Score
from app.schemas.score import MAX_EDIT_DOC_BYTES


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()
NEXT_WEEK = THIS_WEEK + timedelta(days=7)

LEADER_PAYLOAD = {
    "name": "founder",
    "email": "founder@example.com",
    "password": "Password1",
    "church": "Edit Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

OTHER_CHURCH_PAYLOAD = {
    **LEADER_PAYLOAD,
    "email": "stranger@example.com",
    "church": "Other Edit Church",
}

NEW_SCORE = {
    "title": "Amazing Grace",
    "week_of": THIS_WEEK.isoformat(),
    "storage_type": "s3",
    "filename": "score.jpg",
    "content_type": "image/jpeg",
}

# Deliberately not fabric's real shape: the server stores this opaquely, and a
# test written against a shape it does not parse would suggest otherwise.
EDIT_DOC = {"version": "1", "objects": [{"type": "i-text", "text": "3부", "left": 10, "top": 20}]}


def _headers(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}


def _found_church(client, payload: dict = LEADER_PAYLOAD) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return _headers(response.json())


def _create_score(client, headers: dict, payload: dict = NEW_SCORE) -> str:
    response = client.post("/scores", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def _sign_edit_upload(client, headers: dict, score_id: str) -> str:
    response = client.post(f"/scores/{score_id}/edited-file", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["s3_key"]


def _save_edit(client, headers: dict, score_id: str, doc: dict = EDIT_DOC) -> str:
    key = _sign_edit_upload(client, headers, score_id)
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": key, "edit_doc": doc},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return key


def _conti_image_urls(client, headers: dict, week: date) -> list[str | None]:
    response = client.get(f"/weeks/{week.isoformat()}/conti", headers=headers)
    assert response.status_code == 200, response.text
    return [item["image_url"] for page in response.json()["pages"] for item in page]


# --- the signature ------------------------------------------------------


def test_signing_an_edit_upload_should_mint_a_png_under_this_church(client):
    """The caller never names the object. That is what stops this route from
    being a way to have the server sign somebody else's key."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    response = client.post(f"/scores/{score_id}/edited-file", headers=leader)

    # Assert
    assert response.status_code == 200, response.text
    key = response.json()["s3_key"]
    church_id = client.get(f"/scores/{score_id}", headers=leader).json()["church_id"]
    assert key.startswith(f"scores/{church_id}/")
    # png, whatever the song's own file was: a flattened canvas is transparent
    # wherever nothing was drawn, and the score above was filed as a jpeg.
    assert key.endswith(".png")
    assert response.json()["upload_url"].startswith("http")


def test_signing_an_edit_upload_should_not_touch_the_row(client, db_session):
    """The signature is not the save. Until the PUT lands the week still shows
    the sheet it had, so an upload that fails changes nothing."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    _sign_edit_upload(client, leader, score_id)

    # Assert
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri is None
    assert score.edit_doc is None


# --- the save -----------------------------------------------------------


def test_saving_an_edit_should_store_the_picture_and_the_document_together(client, db_session):
    """One without the other is a row nobody can work with: a sheet whose
    markings cannot be taken off, or a document that draws nothing."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    key = _save_edit(client, leader, score_id)

    # Assert
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri == key
    assert score.edit_doc == EDIT_DOC


def test_saving_an_edit_should_change_what_the_conti_draws(client):
    """The point of the whole feature, and the only assertion that crosses
    from the write side to the read side."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    before = _conti_image_urls(client, leader, THIS_WEEK)

    # Act
    key = _save_edit(client, leader, score_id)

    # Assert
    after = _conti_image_urls(client, leader, THIS_WEEK)
    assert len(after) == 1
    assert after != before
    # A presigned URL, so the key is compared rather than the whole string.
    edited_url = after[0]
    assert edited_url is not None
    assert key in edited_url


def test_saving_an_edit_should_leave_the_songs_own_file_alone(client, db_session):
    """The edit belongs to this Sunday. Writing it onto the song would reach
    back into every week that ever used it, including services already held."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    db_session.expire_all()
    song_file_uri = db_session.get(Score, score_id).song.file_uri

    # Act
    _save_edit(client, leader, score_id)

    # Assert
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.song.file_uri == song_file_uri
    # Nor the filing snapshot: that is what the song-split downgrade restores
    # the old table from.
    assert score.file_uri == song_file_uri


def test_saving_an_edit_should_store_the_document_the_client_sent(client, db_session):
    """Stored opaquely. The shape belongs to the editor, and a server that
    reshaped it would silently break a document it did not understand."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    odd_doc = {"nested": {"list": [1, "two", None, {"deep": True}]}, "empty": {}}

    # Act
    _save_edit(client, leader, score_id, doc=odd_doc)

    # Assert
    db_session.expire_all()
    assert db_session.get(Score, score_id).edit_doc == odd_doc


# --- the gate -----------------------------------------------------------


def test_saving_an_edit_should_refuse_another_churchs_key(client, db_session):
    """The signing oracle this gate exists to close.

    conti signs anything under scores/ (build_week_conti_pdf documents why),
    so a key accepted here comes back out as a presigned GET the caller was
    never entitled to. It has to be refused on the way in.
    """
    # Arrange
    leader = _found_church(client)
    stranger = _found_church(client, OTHER_CHURCH_PAYLOAD)
    score_id = _create_score(client, leader)
    foreign_key = _sign_edit_upload(client, stranger, _create_score(client, stranger))

    # Act
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": foreign_key, "edit_doc": EDIT_DOC},
        headers=leader,
    )

    # Assert
    assert response.status_code == 400, response.text
    db_session.expire_all()
    assert db_session.get(Score, score_id).edited_file_uri is None


def test_saving_an_edit_should_refuse_a_key_outside_the_scores_prefix(client):
    """Same gate, the other half: a path that is not in the bucket's score
    space at all."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": "../../etc/passwd", "edit_doc": EDIT_DOC},
        headers=leader,
    )

    # Assert
    assert response.status_code == 400, response.text


def test_editing_another_churchs_score_should_be_not_found(client):
    """404 rather than 403, matching every other cross-church read: 403 would
    confirm the id is real."""
    # Arrange
    leader = _found_church(client)
    stranger = _found_church(client, OTHER_CHURCH_PAYLOAD)
    score_id = _create_score(client, leader)

    # Act / Assert
    assert client.get(f"/scores/{score_id}/edit", headers=stranger).status_code == 404
    assert client.post(f"/scores/{score_id}/edited-file", headers=stranger).status_code == 404
    assert (
        client.put(
            f"/scores/{score_id}/edit",
            json={"edited_file_uri": "scores/x/y.png", "edit_doc": EDIT_DOC},
            headers=stranger,
        ).status_code
        == 404
    )
    assert client.delete(f"/scores/{score_id}/edit", headers=stranger).status_code == 404


def test_saving_an_oversized_document_should_be_refused_before_the_write(client, db_session):
    """Refused at the schema, so an oversized body never reaches the row that
    every conti read touches."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    key = _sign_edit_upload(client, leader, score_id)
    huge = {"objects": ["x" * (MAX_EDIT_DOC_BYTES + 1)]}

    # Act
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": key, "edit_doc": huge},
        headers=leader,
    )

    # Assert
    assert response.status_code == 422, response.text
    db_session.expire_all()
    assert db_session.get(Score, score_id).edit_doc is None


# --- reopening ----------------------------------------------------------


def test_opening_the_editor_should_hand_back_the_songs_file_not_the_edited_one(client):
    """The one that is easy to get backwards.

    The document is replayed over this background. Handing back the edited
    sheet would draw every earlier marking twice — once painted in, once as
    the object that painted it — and the second save would bake the doubling
    in for good.
    """
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    song_key = client.get(f"/scores/{score_id}", headers=leader).json()["file_uri"]
    edited_key = _save_edit(client, leader, score_id)

    # Act
    response = client.get(f"/scores/{score_id}/edit", headers=leader)

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert song_key in body["source_image_url"]
    assert edited_key not in body["source_image_url"]
    assert body["edited_file_uri"] == edited_key
    assert body["edit_doc"] == EDIT_DOC


def test_opening_an_unedited_score_should_report_nothing_drawn(client):
    """A leader opening a sheet for the first time is not an error, and the
    screen needs a background to open onto."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    body = client.get(f"/scores/{score_id}/edit", headers=leader).json()

    # Assert
    assert body["edited_file_uri"] is None
    assert body["edit_doc"] is None
    assert body["source_image_url"] is not None


# --- throwing an edit away ----------------------------------------------


def test_clearing_an_edit_should_take_the_week_back_to_the_songs_sheet(client, db_session):
    """The only way back to unedited: saving an empty canvas still flattens to
    a picture, and the week would go on showing that copy."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    _save_edit(client, leader, score_id)
    song_key = client.get(f"/scores/{score_id}", headers=leader).json()["file_uri"]

    # Act
    response = client.delete(f"/scores/{score_id}/edit", headers=leader)

    # Assert
    assert response.status_code == 200, response.text
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri is None
    assert score.edit_doc is None
    restored_url = _conti_image_urls(client, leader, THIS_WEEK)[0]
    assert restored_url is not None
    assert song_key in restored_url


def test_clearing_an_unedited_score_should_not_be_an_error(client):
    """Pressing 원본으로 twice has not done anything wrong."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)

    # Act / Assert
    assert client.delete(f"/scores/{score_id}/edit", headers=leader).status_code == 200
    assert client.delete(f"/scores/{score_id}/edit", headers=leader).status_code == 200


def test_replacing_the_songs_file_should_drop_the_document_too(client, db_session):
    """The picture being cleared here is already covered elsewhere; what this
    fixes is that the *document* goes with it. A document left behind would be
    replayed over a background it was never drawn on."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    _save_edit(client, leader, score_id)
    new_key = client.post(
        f"/scores/{score_id}/file",
        json={"filename": "rescan.png", "content_type": "image/png"},
        headers=leader,
    ).json()["s3_key"]

    # Act
    response = client.patch(f"/scores/{score_id}", json={"file_uri": new_key}, headers=leader)

    # Assert
    assert response.status_code == 200, response.text
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri is None
    assert score.edit_doc is None


def test_moving_the_usage_to_another_week_should_drop_the_document_too(client, db_session):
    """Same pairing, the other event that invalidates an edit: the markings
    describe the Sunday they were drawn for."""
    # Arrange
    leader = _found_church(client)
    score_id = _create_score(client, leader)
    _save_edit(client, leader, score_id)

    # Act
    response = client.patch(
        f"/scores/{score_id}", json={"week_of": NEXT_WEEK.isoformat()}, headers=leader
    )

    # Assert
    assert response.status_code == 200, response.text
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri is None
    assert score.edit_doc is None
