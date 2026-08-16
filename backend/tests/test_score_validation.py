"""Pins the length caps on score payloads.

The columns are title varchar(255) and file_uri varchar(1024). Postgres
enforces those, so a value that clears validation but not the column blows up
at commit as a DataError — a 500 with the row half-updated in the session,
instead of the 422 the caller can act on. ScoreCreate carried the title cap
from the start; ScoreUpdate did not, so the same edit that was refused on the
way in was accepted on the way through PATCH.
"""

from datetime import date, timedelta

TITLE_MAX = 255
FILE_URI_MAX = 1024


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

SIGNUP_PAYLOAD = {
    "name": "member",
    "email": "member@example.com",
    "password": "Password1",
    "church": "Validation Church",
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


def _register(client, payload: dict = SIGNUP_PAYLOAD) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def _create_score(client, headers: dict) -> str:
    response = client.post("/scores", json=NEW_SCORE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def test_updating_a_title_past_the_column_limit_should_return_422(client):
    """This was the 500: no cap on ScoreUpdate, varchar(255) underneath."""
    headers = _register(client)
    score_id = _create_score(client, headers)

    response = client.patch(
        f"/scores/{score_id}", json={"title": "a" * (TITLE_MAX + 1)}, headers=headers
    )

    assert response.status_code == 422, response.text
    # The refusal must have changed nothing.
    still = client.get(f"/scores/{score_id}", headers=headers)
    assert still.json()["title"] == NEW_SCORE["title"]


def test_updating_a_title_to_the_exact_limit_should_be_accepted(client):
    """The boundary itself is legal — the cap must sit on the column size."""
    headers = _register(client)
    score_id = _create_score(client, headers)

    response = client.patch(
        f"/scores/{score_id}", json={"title": "a" * TITLE_MAX}, headers=headers
    )

    assert response.status_code == 200, response.text


def test_updating_a_title_to_an_empty_string_should_return_422(client):
    """The web form cannot send this (it drops falsy input), so only the API
    path reaches it — which is exactly why the schema has to refuse it."""
    headers = _register(client)
    score_id = _create_score(client, headers)

    response = client.patch(f"/scores/{score_id}", json={"title": ""}, headers=headers)

    assert response.status_code == 422, response.text
    still = client.get(f"/scores/{score_id}", headers=headers)
    assert still.json()["title"] == NEW_SCORE["title"]


def test_creating_a_score_with_an_empty_title_should_return_422(client):
    headers = _register(client)

    response = client.post("/scores", json={**NEW_SCORE, "title": ""}, headers=headers)

    assert response.status_code == 422, response.text


def test_creating_a_score_with_an_oversized_title_should_return_422(client):
    headers = _register(client)

    response = client.post(
        "/scores", json={**NEW_SCORE, "title": "a" * (TITLE_MAX + 1)}, headers=headers
    )

    assert response.status_code == 422, response.text


def test_an_oversized_file_uri_should_return_422_not_500(client):
    """A key under the caller's own prefix clears the ownership gate, so
    without a cap it rides through to commit and the varchar(1024) fires."""
    headers = _register(client)
    church_id = client.get("/auth/me", headers=headers).json()["user"]["church_id"]
    long_key = f"scores/{church_id}/" + "a" * FILE_URI_MAX

    response = client.post(
        "/scores",
        json={
            "title": "long uri",
            "week_of": THIS_WEEK.isoformat(),
            "storage_type": "local",
            "file_uri": long_key,
        },
        headers=headers,
    )

    assert response.status_code == 422, response.text


def test_repointing_at_an_oversized_file_uri_should_return_422_not_500(client):
    """Create and update carry the same cap — a mutation that drops only the
    update one is invisible to the POST test above."""
    headers = _register(client)
    church_id = client.get("/auth/me", headers=headers).json()["user"]["church_id"]
    score_id = _create_score(client, headers)
    long_key = f"scores/{church_id}/" + "a" * FILE_URI_MAX

    response = client.patch(
        f"/scores/{score_id}", json={"file_uri": long_key}, headers=headers
    )

    assert response.status_code == 422, response.text


def test_saving_to_the_library_with_an_oversized_title_should_return_422(client):
    """Second door into the same column: the library upload writes scores.title
    too, and its schema had no cap at all."""
    headers = _register(client)

    response = client.post(
        "/me/saved-scores/upload",
        json={"title": "a" * (TITLE_MAX + 1), "filename": "score.pdf"},
        headers=headers,
    )

    assert response.status_code == 422, response.text


def test_saving_to_the_library_with_an_empty_title_should_return_422(client):
    headers = _register(client)

    response = client.post(
        "/me/saved-scores/upload",
        json={"title": "", "filename": "score.pdf"},
        headers=headers,
    )

    assert response.status_code == 422, response.text
