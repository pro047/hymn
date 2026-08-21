"""Pins the re-upload path: a score that exists can be pointed at a new file.

Until now the only way to get a presigned PUT was POST /scores, which also
creates a row — so replacing the image of an existing score meant deleting it
and filing it again under a new id. This route signs a key for a score that is
already there.

Two properties matter and are fixed here. It mints a *new* key rather than
overwriting the current one, so a failed upload cannot destroy the original.
And it writes nothing: the row still points at the old file until the client
PATCHes file_uri, which it does only after the upload succeeds.
"""

import re
from datetime import date, timedelta

from app.models import Score


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

LEADER_PAYLOAD = {
    "name": "founder",
    "email": "founder@example.com",
    "password": "Password1",
    "church": "Replace Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

NEW_SCORE = {
    "title": "Amazing Grace",
    "week_of": THIS_WEEK.isoformat(),
    "storage_type": "s3",
    "filename": "score.jpg",
    "content_type": "image/jpeg",
}

REPLACEMENT = {"filename": "rescan.png", "content_type": "image/png"}


def _headers(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}


def _found_church(client, payload: dict = LEADER_PAYLOAD) -> tuple[dict, str]:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return _headers(response.json()), response.json()["church"]["code"]


def _join_member(client, code: str, email: str) -> dict:
    response = client.post(
        "/auth/signup", json={**LEADER_PAYLOAD, "email": email, "join_code": code}
    )
    assert response.status_code == 201, response.text
    return _headers(response.json())


def _create_score(client, headers: dict) -> str:
    response = client.post("/scores", json=NEW_SCORE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def test_requesting_a_replacement_upload_should_return_a_new_church_scoped_key(client):
    # Arrange
    leader, _ = _found_church(client)
    created = client.post("/scores", json=NEW_SCORE, headers=leader)
    original_key = created.json()["s3_key"]

    # Act
    response = client.post(
        f"/scores/{created.json()['score_id']}/file", json=REPLACEMENT, headers=leader
    )

    # Assert
    assert response.status_code == 200, response.text
    key = response.json()["s3_key"]
    assert re.fullmatch(r"scores/[0-9a-f-]{36}/[0-9a-f-]{36}\.png", key), key
    # Same church prefix, different object: overwriting in place would destroy
    # the original before the new bytes are known to be good.
    assert key.rsplit("/", 1)[0] == original_key.rsplit("/", 1)[0]
    assert key != original_key
    assert response.json()["upload_url"].startswith("http")


def test_requesting_a_replacement_upload_should_not_touch_the_row(client, db_session):
    """The signature is not the edit. The score keeps its file until the client
    PATCHes, which it does only once the upload has succeeded."""
    # Arrange
    leader, _ = _found_church(client)
    score_id = _create_score(client, leader)
    before = db_session.get(Score, score_id).file_uri

    # Act
    client.post(f"/scores/{score_id}/file", json=REPLACEMENT, headers=leader)

    # Assert
    db_session.expire_all()
    assert db_session.get(Score, score_id).file_uri == before


def test_patching_the_signed_key_should_move_the_score_onto_the_new_file(client):
    """The two calls together are the feature; neither does it alone."""
    # Arrange
    leader, _ = _found_church(client)
    score_id = _create_score(client, leader)
    key = client.post(f"/scores/{score_id}/file", json=REPLACEMENT, headers=leader).json()[
        "s3_key"
    ]

    # Act
    patched = client.patch(f"/scores/{score_id}", json={"file_uri": key}, headers=leader)

    # Assert
    assert patched.status_code == 200, patched.text
    assert patched.json()["file_uri"] == key
    # download_url is minted from the stored key, so this is what the client
    # would actually render.
    assert key in patched.json()["download_url"]
    # file_url must stay a URL. Every client reads `download_url ?? file_url`,
    # and create_score writes object_url() there — storing the bare key made the
    # two paths disagree, and only the scores/ prefix (which is what makes
    # _download_url sign it) kept the fallback from ever being reached.
    file_url = patched.json()["file_url"]
    assert file_url.startswith("http"), file_url
    assert file_url.endswith(key), file_url


def test_requesting_a_replacement_for_another_churchs_score_should_return_404(client):
    """404 rather than 403, matching _own_score_or_404: 403 would confirm the id
    is real to someone outside the congregation."""
    # Arrange
    owner, _ = _found_church(client)
    score_id = _create_score(client, owner)
    outsider, _ = _found_church(
        client,
        {**LEADER_PAYLOAD, "email": "other@example.com", "church": "Other Church"},
    )

    # Act
    response = client.post(f"/scores/{score_id}/file", json=REPLACEMENT, headers=outsider)

    # Assert
    assert response.status_code == 404, response.text


def test_requesting_a_replacement_for_a_fellow_members_score_should_return_403(client):
    """Same gate as PATCH and DELETE — the file is as much an edit as the title,
    so it must not be the one write a member can make on someone else's row."""
    # Arrange
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    other = _join_member(client, code, "other@example.com")
    score_id = _create_score(client, uploader)

    # Act
    response = client.post(f"/scores/{score_id}/file", json=REPLACEMENT, headers=other)

    # Assert
    assert response.status_code == 403, response.text


def test_a_member_should_replace_the_file_of_their_own_upload(client):
    """The gate must not close the path it exists to protect."""
    # Arrange
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    score_id = _create_score(client, uploader)

    # Act
    response = client.post(f"/scores/{score_id}/file", json=REPLACEMENT, headers=uploader)

    # Assert
    assert response.status_code == 200, response.text


def test_requesting_a_replacement_without_a_filename_should_return_422(client):
    """ScoreCreate tolerates a missing filename because it also serves the local
    branch; here there is nothing to derive an extension from."""
    # Arrange
    leader, _ = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    response = client.post(
        f"/scores/{score_id}/file", json={"content_type": "image/png"}, headers=leader
    )

    # Assert
    assert response.status_code == 422, response.text


def test_requesting_a_replacement_without_a_token_should_return_401(client):
    # Arrange
    leader, _ = _found_church(client)
    score_id = _create_score(client, leader)

    # Act
    response = client.post(f"/scores/{score_id}/file", json=REPLACEMENT)

    # Assert
    assert response.status_code == 401, response.text
