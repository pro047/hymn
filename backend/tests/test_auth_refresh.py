SIGNUP_PAYLOAD = {
    "name": "tester",
    "email": "tester@example.com",
    "password": "Password1",
    "church": "Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _signup(client) -> dict:
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def test_refresh_returns_rotated_token_pair(client):
    tokens = _signup(client)

    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != tokens["refresh_token"]


def test_refresh_token_cannot_be_reused_after_rotation(client):
    tokens = _signup(client)

    first = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200, first.text

    reuse = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401

    rotated = first.json()["refresh_token"]
    second = client.post("/auth/refresh", json={"refresh_token": rotated})
    assert second.status_code == 200, second.text


def test_logout_revokes_refresh_token(client):
    tokens = _signup(client)

    logout = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204

    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_login_issued_refresh_token_is_valid(client):
    _signup(client)

    login = client.post(
        "/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )
    assert login.status_code == 200, login.text
    refresh_token = login.json()["tokens"]["refresh_token"]

    response = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200, response.text
