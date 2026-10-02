"""Pins the shape a storage key must have before a write route will take it.

The gate was a prefix test, `scores/{church}/`, and a prefix says nothing about
what follows it. `scores/{mine}/../{theirs}/x.png` starts correctly and names
another church's object; `scores/{mine}/` names no object at all.

Every key this server mints is exactly `scores/{church}/{name}`, so the gate
now asks for exactly that: three segments, the middle one the caller's church,
none of them empty or a dot segment.
"""

from datetime import date, timedelta

import pytest

from app.models import Score, Song
from app.routes import score as score_routes
from song_helpers import file_usage


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

CHURCH_A_PAYLOAD = {
    "name": "leader a",
    "email": "leader-a@example.com",
    "password": "Password1",
    "church": "Key Church A",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

CHURCH_B_PAYLOAD = {
    **CHURCH_A_PAYLOAD,
    "name": "leader b",
    "email": "leader-b@example.com",
    "church": "Key Church B",
}

BAD_KEY_BODY = {"detail": "잘못된 파일 경로입니다."}
EDIT_DOC = {"objects": []}

ACCEPTED_KEYS = [
    "scores/c1/x.png",
    "scores/c1/0a1b.pdf",
    # Dots inside a name are a name. Only a whole segment of them is a step.
    "scores/c1/a..b.png",
]

REFUSED_KEYS = [
    "scores/c1/../c2/x.png",
    "scores/c1/",
    "scores/c1/a/b.png",
    "scores/c1/..",
    "scores/c1/.",
    "scores/c2/x.png",
    "scores/c1x/x.png",
    "scores/c/x.png",
    "/scores/c1/x.png",
    "scores//x.png",
    "x/c1/x.png",
    "scores",
    "",
    "scores/../x.png",
    "etc/passwd",
    "scores/c1/x.png/",
    "scores/c1/./x.png",
    "Scores/c1/x.png",
    "scores/c1",
]


def _signup(client, payload: dict) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _headers(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['tokens']['access_token']}"}


def _own_score_and_a_foreign_church(client) -> tuple[dict, str, str, str]:
    """(A's headers, A's score id, A's church id, B's church id)."""
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    headers = _headers(a)
    score_id = file_usage(client, headers, title="Amazing Grace", week=THIS_WEEK).json()["score_id"]
    return headers, score_id, a["user"]["church_id"], b["user"]["church_id"]


def _malformed_keys(own: str, foreign: str) -> dict[str, str]:
    """Keys that all start with the caller's own prefix and are still wrong."""
    return {
        "traversal": f"scores/{own}/../{foreign}/x.png",
        "empty-name": f"scores/{own}/",
        "nested": f"scores/{own}/a/b.png",
        "dot-dot-name": f"scores/{own}/..",
        "dot-name": f"scores/{own}/.",
    }


MALFORMED = ["traversal", "empty-name", "nested", "dot-dot-name", "dot-name"]


# --- the rule itself -----------------------------------------------------


@pytest.mark.parametrize("key", ACCEPTED_KEYS)
def test_a_three_segment_key_of_the_church_should_be_recognised(key):
    assert score_routes.is_church_object_key(key, "c1") is True


@pytest.mark.parametrize("key", REFUSED_KEYS)
def test_a_key_of_any_other_shape_should_not_be_recognised(key):
    assert score_routes.is_church_object_key(key, "c1") is False


# --- through PATCH /scores/{id} ------------------------------------------


@pytest.mark.parametrize("shape", MALFORMED)
def test_repointing_a_score_at_a_malformed_own_prefix_key_should_return_400(client, db_session, shape):
    # Arrange
    headers, score_id, own, foreign = _own_score_and_a_foreign_church(client)
    key = _malformed_keys(own, foreign)[shape]
    before = client.get(f"/scores/{score_id}", headers=headers).json()["file_uri"]

    # Act
    response = client.patch(f"/scores/{score_id}", json={"file_uri": key}, headers=headers)

    # Assert — refused, and neither the usage nor the song moved.
    assert response.status_code == 400, response.text
    assert response.json() == BAD_KEY_BODY
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.file_uri == before
    assert db_session.get(Song, score.song_id).file_uri == before
    assert client.get(f"/scores/{score_id}", headers=headers).json()["file_uri"] == before


def test_repointing_a_score_at_a_well_formed_own_key_should_be_accepted(client):
    # Arrange
    headers, score_id, own, _ = _own_score_and_a_foreign_church(client)
    key = f"scores/{own}/mine.png"

    # Act
    response = client.patch(f"/scores/{score_id}", json={"file_uri": key}, headers=headers)

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["file_uri"] == key


# --- through PUT /scores/{id}/edit ---------------------------------------


@pytest.mark.parametrize("shape", MALFORMED)
def test_saving_an_edit_under_a_malformed_own_prefix_key_should_return_400(client, db_session, shape):
    # Arrange
    headers, score_id, own, foreign = _own_score_and_a_foreign_church(client)
    key = _malformed_keys(own, foreign)[shape]

    # Act
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": key, "edit_doc": EDIT_DOC},
        headers=headers,
    )

    # Assert
    assert response.status_code == 400, response.text
    assert response.json() == BAD_KEY_BODY
    db_session.expire_all()
    score = db_session.get(Score, score_id)
    assert score.edited_file_uri is None
    assert score.edit_doc is None


def test_saving_an_edit_under_a_well_formed_own_key_should_be_accepted(client, db_session):
    # Arrange
    headers, score_id, own, _ = _own_score_and_a_foreign_church(client)
    key = f"scores/{own}/edited.png"

    # Act
    response = client.put(
        f"/scores/{score_id}/edit",
        json={"edited_file_uri": key, "edit_doc": EDIT_DOC},
        headers=headers,
    )

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["edited_file_uri"] == key
    db_session.expire_all()
    assert db_session.get(Score, score_id).edited_file_uri == key
