import re

SIGNUP_PAYLOAD = {
    "name": "uploader",
    "email": "uploader@example.com",
    "password": "Password1",
    "church": "Key Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _auth_headers(client) -> dict:
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def test_s3_key_contains_church_scope_not_placeholder(client):
    # The church comes from the token now; the request cannot name one.
    headers = _auth_headers(client)

    response = client.post(
        "/scores",
        json={
            "title": "Amazing Grace",
            "week_of": "2026-07-19",
            "storage_type": "s3",
            "filename": "score.pdf",
            "content_type": "application/pdf",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    s3_key = response.json()["s3_key"]

    assert "..." not in s3_key
    assert re.fullmatch(r"scores/[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf", s3_key), s3_key
