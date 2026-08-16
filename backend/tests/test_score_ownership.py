"""Pins who inside a church may modify whose scores.

The church-scope check alone let any member edit or delete any score of their
congregation — the tenancy boundary was the only boundary. Now a score carries
its uploader, a member may modify only their own uploads, and the leader may
modify all of the church's. Reads stay church-wide: the refusal is about the
write, not about hiding the row from people who already share it.

Rows predating uploader_id hold NULL there and so fall to the leader. That
matches production: every legacy row was uploaded by the one account that
exists, and that account leads its church.
"""

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
    "church": "Ownership Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

NEW_SCORE = {
    "title": "Amazing Grace",
    "week_of": THIS_WEEK.isoformat(),
    "storage_type": "s3",
    "filename": "score.pdf",
    "content_type": "application/pdf",
}


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
    response = client.post("/scores", json=score, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def _user_id(client, headers: dict) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["id"]


def test_a_created_score_should_carry_its_uploader(client, db_session):
    leader, _ = _found_church(client)

    score_id = _create_score(client, leader)

    row = db_session.get(Score, score_id)
    assert row.uploader_id == _user_id(client, leader)


def test_a_local_score_should_carry_its_uploader_too(client, db_session):
    """The route creates the row in two branches; each must set the field, or
    ownership silently regresses for one storage type only."""
    leader, _ = _found_church(client)
    church_id = client.get("/auth/me", headers=leader).json()["user"]["church_id"]

    score_id = _create_score(
        client,
        leader,
        {
            "title": "local upload",
            "week_of": THIS_WEEK.isoformat(),
            "storage_type": "local",
            "file_uri": f"scores/{church_id}/mine.pdf",
        },
    )

    row = db_session.get(Score, score_id)
    assert row.uploader_id == _user_id(client, leader)


def test_editing_a_fellow_members_score_should_return_403(client):
    """403 rather than 404: a member can already read the score, so its
    existence is not the secret — only the write is refused."""
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    other = _join_member(client, code, "other@example.com")
    score_id = _create_score(client, uploader)

    response = client.patch(f"/scores/{score_id}", json={"title": "hijacked"}, headers=other)

    assert response.status_code == 403, response.text
    still = client.get(f"/scores/{score_id}", headers=uploader)
    assert still.json()["title"] == NEW_SCORE["title"]


def test_deleting_a_fellow_members_score_should_return_403(client):
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    other = _join_member(client, code, "other@example.com")
    score_id = _create_score(client, uploader)

    response = client.delete(f"/scores/{score_id}", headers=other)

    assert response.status_code == 403, response.text
    assert client.get(f"/scores/{score_id}", headers=uploader).status_code == 200


def test_a_member_should_still_modify_their_own_upload(client):
    """The gate must not close the path it exists to protect."""
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    score_id = _create_score(client, uploader)

    renamed = client.patch(f"/scores/{score_id}", json={"title": "내 악보"}, headers=uploader)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "내 악보"

    deleted = client.delete(f"/scores/{score_id}", headers=uploader)
    assert deleted.status_code == 204, deleted.text


def test_the_leader_should_modify_any_score_of_the_church(client):
    """The leader curates the church's library, whoever filed the row."""
    leader, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    score_id = _create_score(client, uploader)

    renamed = client.patch(f"/scores/{score_id}", json={"title": "정리됨"}, headers=leader)
    assert renamed.status_code == 200, renamed.text

    deleted = client.delete(f"/scores/{score_id}", headers=leader)
    assert deleted.status_code == 204, deleted.text


def test_a_legacy_score_with_no_uploader_should_fall_to_the_leader(client, db_session):
    """Rows from before uploader_id existed hold NULL there. NULL matches no
    member id, so members are refused; the leader branch never looks at it."""
    leader, code = _found_church(client)
    member = _join_member(client, code, "member@example.com")
    score_id = _create_score(client, leader)
    db_session.query(Score).filter(Score.id == score_id).update({"uploader_id": None})

    refused = client.patch(f"/scores/{score_id}", json={"title": "denied"}, headers=member)
    assert refused.status_code == 403, refused.text

    allowed = client.patch(f"/scores/{score_id}", json={"title": "정리됨"}, headers=leader)
    assert allowed.status_code == 200, allowed.text


def test_a_member_should_still_read_a_fellow_members_score(client):
    """The write gate must not narrow reads: the church shares its library."""
    _, code = _found_church(client)
    uploader = _join_member(client, code, "uploader@example.com")
    other = _join_member(client, code, "other@example.com")
    score_id = _create_score(client, uploader)

    response = client.get(f"/scores/{score_id}", headers=other)

    assert response.status_code == 200, response.text
