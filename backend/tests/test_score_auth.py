"""Pins who may write to /scores.

Every write used to be anonymous: the route took a church id, or a free-text
church name it would create on the spot, and asked for no credentials at all.
Anyone who could reach the API could file scores under any congregation, edit
them, or delete them.

Reads stay open on purpose. The Android tablets in use call GET /scores with no
authentication and have no login screen to add one, so closing that would brick
them until every device is reinstalled. Writes are safe to close today precisely
because the app never makes one.
"""

from datetime import date, timedelta

from app.schemas.score import current_week_start


def _this_week_sunday() -> date:
    """Worked out here rather than imported from the code under test.

    Asking current_week_start() what this week is makes the expectation move
    with the implementation: break the formula and this constant breaks the
    same way, so the assertions still agree. Relative to today rather than
    hardcoded, though — a fixed week silently ages into the past and the whole
    file would start failing on a date nobody chose.
    """
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

SIGNUP_PAYLOAD = {
    "name": "member",
    "email": "member@example.com",
    "password": "Password1",
    "church": "Score Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

OTHER_CHURCH_PAYLOAD = {
    **SIGNUP_PAYLOAD,
    "name": "outsider",
    "email": "outsider@example.com",
    "church": "Other Church",
}

NEW_SCORE = {
    "title": "Amazing Grace",
    "week_of": THIS_WEEK.isoformat(),
    "storage_type": "s3",
    "filename": "score.pdf",
    "content_type": "application/pdf",
}


def _register(client, payload: dict) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def _create_score(client, headers: dict) -> str:
    response = client.post("/scores", json=NEW_SCORE, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["score_id"]


def test_creating_a_score_without_a_token_should_return_401(client):
    response = client.post("/scores", json=NEW_SCORE)

    assert response.status_code == 401, response.text


def test_updating_a_score_without_a_token_should_return_401(client):
    score_id = _create_score(client, _register(client, SIGNUP_PAYLOAD))

    response = client.patch(f"/scores/{score_id}", json={"title": "hijacked"})

    assert response.status_code == 401, response.text


def test_deleting_a_score_without_a_token_should_return_401(client):
    score_id = _create_score(client, _register(client, SIGNUP_PAYLOAD))

    response = client.delete(f"/scores/{score_id}")

    assert response.status_code == 401, response.text


def test_a_created_score_should_belong_to_the_church_on_the_token(client):
    """The request cannot name a church, so it cannot pick someone else's."""
    headers = _register(client, SIGNUP_PAYLOAD)
    session = client.get("/auth/me", headers=headers)
    assert session.status_code == 200, session.text

    score_id = _create_score(client, headers)

    created = client.get(f"/scores/{score_id}")
    assert created.json()["church_id"] == session.json()["user"]["church_id"]


def test_a_church_name_in_the_body_should_be_ignored_rather_than_honoured(client):
    """The old field is gone; pydantic drops unknown keys rather than erroring,
    so the risk is that it is silently honoured. It must not be."""
    headers = _register(client, SIGNUP_PAYLOAD)

    response = client.post(
        "/scores",
        json={**NEW_SCORE, "church_name": "Somebody Elses Church", "church_id": "forged"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    created = client.get(f"/scores/{response.json()['score_id']}")
    assert created.json()["church_id"] != "forged"
    assert "Somebody Elses Church" not in created.text


def test_updating_a_score_of_another_church_should_return_404(client):
    owner = _register(client, SIGNUP_PAYLOAD)
    score_id = _create_score(client, owner)
    outsider = _register(client, OTHER_CHURCH_PAYLOAD)

    response = client.patch(f"/scores/{score_id}", json={"title": "hijacked"}, headers=outsider)

    # 404, not 403: 403 would confirm the id names a real score.
    assert response.status_code == 404, response.text
    assert client.get(f"/scores/{score_id}").json()["title"] == NEW_SCORE["title"]


def test_deleting_a_score_of_another_church_should_return_404(client):
    owner = _register(client, SIGNUP_PAYLOAD)
    score_id = _create_score(client, owner)
    outsider = _register(client, OTHER_CHURCH_PAYLOAD)

    response = client.delete(f"/scores/{score_id}", headers=outsider)

    assert response.status_code == 404, response.text
    assert client.get(f"/scores/{score_id}").status_code == 200


def test_listing_scores_should_stay_open_to_anonymous_callers(client):
    """The tablets in the field depend on this. Closing it needs an app release
    first — see the staged plan in .claude/handoff.md."""
    _create_score(client, _register(client, SIGNUP_PAYLOAD))

    response = client.get("/scores")

    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


def test_reading_one_score_should_stay_open_to_anonymous_callers(client):
    score_id = _create_score(client, _register(client, SIGNUP_PAYLOAD))

    response = client.get(f"/scores/{score_id}")

    assert response.status_code == 200, response.text


def test_creating_a_score_for_a_past_week_should_return_422(client):
    """A week that has already gone by is a mis-click, not a filing."""
    headers = _register(client, SIGNUP_PAYLOAD)
    last_week = (THIS_WEEK - timedelta(days=7)).isoformat()

    response = client.post("/scores", json={**NEW_SCORE, "week_of": last_week}, headers=headers)

    assert response.status_code == 422, response.text
    assert "지난 주차" in response.text


def test_creating_a_score_for_the_current_week_should_be_accepted(client):
    """The floor is this week's Sunday, not today.

    A week is named by its Sunday, so mid-week that Sunday is already past by
    date — rejecting it would block the week the user is working on.
    """
    headers = _register(client, SIGNUP_PAYLOAD)

    response = client.post(
        "/scores", json={**NEW_SCORE, "week_of": THIS_WEEK.isoformat()}, headers=headers
    )

    assert response.status_code == 200, response.text


def test_moving_a_score_into_a_past_week_should_return_422(client):
    """Otherwise the rule is trivially sidestepped by creating then editing."""
    headers = _register(client, SIGNUP_PAYLOAD)
    score_id = _create_score(client, headers)
    last_week = (THIS_WEEK - timedelta(days=7)).isoformat()

    response = client.patch(f"/scores/{score_id}", json={"week_of": last_week}, headers=headers)

    assert response.status_code == 422, response.text


def test_current_week_start_should_snap_back_to_sunday():
    """Fixed dates, so the formula itself is pinned rather than restated.

    A week is named by its Sunday; getting this off by a day would reject the
    week the user is working on, and no relative-date test can see that.
    """
    assert current_week_start(date(2026, 8, 2)) == date(2026, 8, 2)  # Sunday
    assert current_week_start(date(2026, 8, 6)) == date(2026, 8, 2)  # Thursday
    assert current_week_start(date(2026, 8, 8)) == date(2026, 8, 2)  # Saturday
    assert current_week_start(date(2026, 9, 1)) == date(2026, 8, 30)  # across a month
