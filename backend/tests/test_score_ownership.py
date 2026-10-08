"""Pins who inside a church may modify its scores: the leader, and nobody else.

The church-scope check alone let any member edit or delete any score of their
congregation — the tenancy boundary was the only boundary. A member could then
modify their own uploads; since 2026-10 a member modifies nothing, because only
the leader uploads and arranges (test_leader_only pins that route by route).
Reads stay church-wide: the refusal is about the write, not about hiding the
row from people who already share it.

A score still records who filed it. Rows predating uploader_id hold NULL
there, which no longer decides anything: the leader may modify every row.
"""

from datetime import date, timedelta

from app.models import Score
from song_helpers import file_usage


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

LEADER_PAYLOAD = {
    "name": "founder",
    "email": "founder@example.com",
    "password": "Password1",
    "church": "Ownership Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

NEW_SCORE = {"title": "Amazing Grace", "week_of": THIS_WEEK.isoformat()}


def _headers(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}


def _found_church(client) -> tuple[dict, str]:
    """First account of the church: its headers and the invite code."""
    response = client.post("/auth/signup", json=LEADER_PAYLOAD)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "leader"
    return _headers(body), body["church"]["code"]


def _join_member(client, code: str, email: str) -> dict:
    response = client.post(
        "/auth/signup", json={**LEADER_PAYLOAD, "email": email, "join_code": code}
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "member"
    return _headers(response.json())


def _create_score(client, headers: dict, score: dict = NEW_SCORE) -> str:
    return file_usage(client, headers, title=score["title"], week=score["week_of"]).json()[
        "score_id"
    ]


def _user_id(client, headers: dict) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["id"]


def test_a_created_score_should_carry_its_uploader(client, db_session):
    leader, _ = _found_church(client)

    score_id = _create_score(client, leader)

    row = db_session.get(Score, score_id)
    assert row.uploader_id == _user_id(client, leader)


def test_a_member_editing_a_score_should_return_403(client):
    """403 rather than 404: a member can already read the score, so its
    existence is not the secret — only the write is refused."""
    leader, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")
    score_id = _create_score(client, leader)

    response = client.patch(f"/scores/{score_id}", json={"title": "hijacked"}, headers=member)

    assert response.status_code == 403, response.text
    still = client.get(f"/scores/{score_id}", headers=leader)
    assert still.json()["title"] == NEW_SCORE["title"]


def test_a_member_deleting_a_score_should_return_403(client):
    leader, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")
    score_id = _create_score(client, leader)

    response = client.delete(f"/scores/{score_id}", headers=member)

    assert response.status_code == 403, response.text
    assert client.get(f"/scores/{score_id}", headers=leader).status_code == 200


def test_a_member_should_not_file_a_score_of_their_own(client):
    """Was "a member should still modify their own upload". A member has no
    upload to modify any more: filing a song is itself the leader's."""
    _, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")

    uploaded = client.post(
        "/songs",
        json={"title": NEW_SCORE["title"], "filename": "score.png", "content_type": "image/png"},
        headers=member,
    )

    assert uploaded.status_code == 403, uploaded.text
    assert client.get("/scores", headers=member).json() == []


def test_the_leader_should_modify_any_score_of_the_church(client):
    """The leader curates the church's library."""
    leader, _ = _found_church(client)
    score_id = _create_score(client, leader)

    renamed = client.patch(f"/scores/{score_id}", json={"title": "정리됨"}, headers=leader)
    assert renamed.status_code == 200, renamed.text

    deleted = client.delete(f"/scores/{score_id}", headers=leader)
    assert deleted.status_code == 204, deleted.text


def test_a_legacy_score_with_no_uploader_should_fall_to_the_leader(client, db_session):
    """Rows from before uploader_id existed hold NULL there. Nothing reads the
    column to decide a write, so such a row behaves like any other: refused to
    a member, the leader's to modify."""
    leader, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")
    score_id = _create_score(client, leader)
    db_session.query(Score).filter(Score.id == score_id).update({"uploader_id": None})

    refused = client.patch(f"/scores/{score_id}", json={"title": "denied"}, headers=member)
    assert refused.status_code == 403, refused.text

    allowed = client.patch(f"/scores/{score_id}", json={"title": "정리됨"}, headers=leader)
    assert allowed.status_code == 200, allowed.text


def test_a_member_should_still_read_the_churchs_score(client):
    """The write gate must not narrow reads: the church shares its scores."""
    leader, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")
    score_id = _create_score(client, leader)

    response = client.get(f"/scores/{score_id}", headers=member)

    assert response.status_code == 200, response.text
