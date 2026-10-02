"""Pins which church GET /auth/me reports.

The answer carried two churches from two sources: `user.church_id` read off
the row, and `church` looked up by the id in the token's claims. They agree
until the row changes under a token that is still valid, and then the session
describes a user in one church and shows the name and invite code of another.

The row is the truth; the claim is only what was true when the token was
minted.
"""

from app.deps import SESSION_EXPIRED_MESSAGE
from app.models import User
from app.services.auth import _encode_token

CHURCH_A_PAYLOAD = {
    "name": "leader a",
    "email": "leader-a@example.com",
    "password": "Password1",
    "church": "Session Church A",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

CHURCH_B_PAYLOAD = {
    **CHURCH_A_PAYLOAD,
    "name": "leader b",
    "email": "leader-b@example.com",
    "church": "Session Church B",
}


def _signup(client, payload: dict) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _headers(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['tokens']['access_token']}"}


def test_me_should_report_the_church_on_the_user_row_not_the_one_in_the_token(client, db_session):
    # Arrange — A's row moves to church B; token_version is left alone, so the
    # token minted under church A is still accepted.
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    b_church_id = b["user"]["church_id"]
    assert b_church_id != a["user"]["church_id"]
    db_session.query(User).filter(User.id == a["user"]["id"]).update({"church_id": b_church_id})
    db_session.expire_all()

    # Act
    response = client.get("/auth/me", headers=_headers(a))

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["id"] == a["user"]["id"]
    assert body["user"]["church_id"] == b_church_id
    assert body["church"]["id"] == b_church_id
    assert body["church"]["name"] == "Session Church B"
    # A is a leader, so a code is shown — and it has to be this church's.
    assert body["church"]["code"] == b["church"]["code"]


def test_me_should_report_the_users_own_church_when_nothing_has_moved(client):
    # Arrange
    a = _signup(client, CHURCH_A_PAYLOAD)
    _signup(client, CHURCH_B_PAYLOAD)

    # Act
    response = client.get("/auth/me", headers=_headers(a))

    # Assert
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["church_id"] == a["user"]["church_id"]
    assert body["church"]["id"] == a["user"]["church_id"]
    assert body["church"]["name"] == "Session Church A"
    assert body["church"]["code"] == a["church"]["code"]


def test_me_should_still_refuse_a_token_with_no_church_claim(client):
    """The lookup stops using the claim; the check that it is there stays."""
    # Arrange
    a = _signup(client, CHURCH_A_PAYLOAD)
    claimless = _encode_token(
        {"sub": a["user"]["id"], "role": "leader", "type": "access", "tv": 0},
        expires_in=600,
    )

    # Act
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {claimless}"})

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": SESSION_EXPIRED_MESSAGE}
