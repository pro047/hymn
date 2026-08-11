"""Pins /auth/password: who may change it, what it accepts, what it invalidates.

Before this the only way to change a password was to write a bcrypt hash into
the database over SSM, which is how the one production account got its current
one. The rules a new password has to clear are signup's, shared rather than
copied, so test_auth_signup.py still owns the cases for the rules themselves —
what is here is the change route, and the session decision it makes: everything
out, the caller included, with nothing issued in return — refresh tokens *and*
the access tokens already handed out, retired through the user's token_version.
"""

from app.rate_limit import PASSWORD_CHANGE_LIMIT

PASSWORD_CHANGES_PER_MINUTE = int(PASSWORD_CHANGE_LIMIT.split("/")[0])

CURRENT_PASSWORD = "Password1"
NEW_PASSWORD = "Newpassword1"

SIGNUP_PAYLOAD = {
    "name": "tester",
    "email": "tester@example.com",
    "password": CURRENT_PASSWORD,
    "church": "Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

CALLER = {"X-Real-IP": "203.0.113.10"}


def _signup(client) -> dict:
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def _login(client, password: str):
    return client.post(
        "/auth/login", json={"email": SIGNUP_PAYLOAD["email"], "password": password}
    )


def _change(client, access_token: str, **overrides):
    body = {"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD, **overrides}
    return client.post(
        "/auth/password", json=body, headers={"Authorization": f"Bearer {access_token}"}
    )


def _bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _detail_for(response, field: str) -> dict:
    return next(item for item in response.json()["detail"] if item["loc"][-1] == field)


def test_changing_the_password_without_a_token_should_return_401(client):
    _signup(client)

    response = client.post(
        "/auth/password",
        json={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    # 401 here and 403 for a wrong password, and the pair has to stay split:
    # the web client refreshes and retries on 401 and signs the user out when
    # that fails, which is right for a dead session and wrong for a typo.
    assert response.status_code == 401, response.text
    # And the account is untouched — an unauthenticated 401 that still wrote
    # would be a way to reset any password from off the street.
    assert _login(client, CURRENT_PASSWORD).status_code == 200


def test_a_wrong_current_password_should_return_403_and_change_nothing(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], current_password="Wrongpass1")

    # 403 rather than 401, and the web client is why: it reads a 401 as an
    # expired session, refreshes, retries, gets the same answer and signs the
    # user out. One typo would then cost them their session.
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "현재 비밀번호가 올바르지 않습니다."
    # The status code alone passes even if the route wrote the new hash and
    # then failed on the way out. These two are what actually say it did not:
    # the old password still opens the account and the new one does not.
    assert _login(client, CURRENT_PASSWORD).status_code == 200
    assert _login(client, NEW_PASSWORD).status_code == 401


def test_a_nul_byte_in_the_current_password_should_return_403_not_500(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], current_password="Passwo\x00rd1")

    # bcrypt refuses NUL and passlib raises rather than answering False.
    # current_password carries no control-character rule on purpose, so an
    # authenticated caller can reach it; uncaught it is a 500 on a live route.
    assert response.status_code == 403, response.text
    assert _login(client, CURRENT_PASSWORD).status_code == 200


def test_a_new_password_without_mixed_case_should_return_422(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], new_password="newpassword1")

    assert response.status_code == 422, response.text
    item = _detail_for(response, "new_password")
    assert item["type"] == "value_error"
    assert "영문 대문자와 소문자" in item["msg"]


def test_a_short_new_password_should_be_reported_as_a_length_violation(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], new_password="Newp1")

    assert response.status_code == 422, response.text
    # string_too_short, not value_error: the client reads ctx.min_length to word
    # its own sentence. Measuring the length inside the strength validator
    # instead would collapse it to value_error and break that wording.
    item = _detail_for(response, "new_password")
    assert item["type"] == "string_too_short"
    assert item["ctx"]["min_length"] == 8


def test_a_new_password_with_a_control_character_should_return_422(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], new_password="Newpass\nword1")

    assert response.status_code == 422, response.text
    assert "제어 문자" in _detail_for(response, "new_password")["msg"]


def test_a_new_password_equal_to_the_current_one_should_return_422(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], new_password=CURRENT_PASSWORD)

    assert response.status_code == 422, response.text
    # Cross-field, so pydantic files it against the model rather than a field:
    # loc is ("body",) and the client renders it as a form-level alert.
    assert "새 비밀번호가 현재 비밀번호와 같습니다." in response.text


def test_a_rejected_password_change_should_not_echo_either_password(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"], new_password=CURRENT_PASSWORD)

    assert response.status_code == 422
    # The model validator's `input` is the whole body, both live credentials in
    # it, and this is the one 422 on the route that carries the current password
    # as well as the new one. The handler in main.py strips `input`; this is
    # what fails if that ever stops covering model-level errors.
    assert CURRENT_PASSWORD not in response.text


def test_changing_the_password_should_replace_the_old_one(client):
    tokens = _signup(client)

    response = _change(client, tokens["access_token"])

    assert response.status_code == 204, response.text
    assert _login(client, CURRENT_PASSWORD).status_code == 401
    assert _login(client, NEW_PASSWORD).status_code == 200


def test_changing_the_password_should_kill_the_callers_access_token(client):
    tokens = _signup(client)
    access = tokens["access_token"]

    # The access token still opens the account right up until the change.
    before = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert before.status_code == 200, before.text

    changed = _change(client, access)
    assert changed.status_code == 204, changed.text

    # And is dead the instant it lands, not an hour later when it expires. The
    # change bumped token_version, so this stateless JWT no longer matches — the
    # gap that let a stolen access token outlive the password meant to lock it
    # out. A 404 here (user missing) would be the wrong reason; it must be 401.
    after = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert after.status_code == 401, after.text


def test_the_dead_access_token_should_be_rejected_on_get_current_user_routes_too(client):
    """/me decodes for itself; the version gate must also hold on the shared
    get_current_user dependency, which every other protected route uses."""
    tokens = _signup(client)
    access = tokens["access_token"]
    # A get_current_user route, open to the founding leader before the change.
    assert client.post("/auth/church/join-code", headers=_bearer(access)).status_code == 200

    _change(client, access)

    # Same token, now one version behind, on a get_current_user route: 401. If
    # the check lived only on /me, this would rotate the church's code with a
    # token the password change was supposed to have killed.
    assert client.post("/auth/church/join-code", headers=_bearer(access)).status_code == 401


def test_signing_back_in_after_a_change_should_yield_a_working_token(client):
    """The bump must not lock the user out of the account they just re-secured.

    A new login mints a token at the current version, so it has to match. If
    access tokens stopped carrying their version, the fresh token would read as
    version 0 against a bumped user and 401 the moment it was issued.
    """
    tokens = _signup(client)
    _change(client, tokens["access_token"])

    login = _login(client, NEW_PASSWORD)
    assert login.status_code == 200, login.text
    fresh = login.json()["tokens"]["access_token"]

    assert client.get("/auth/me", headers=_bearer(fresh)).status_code == 200


def test_changing_the_password_should_revoke_the_other_sessions(client):
    other_device = _signup(client)["refresh_token"]
    this_device = _login(client, CURRENT_PASSWORD).json()["tokens"]

    changed = _change(client, this_device["access_token"])
    assert changed.status_code == 204, changed.text

    # Most password changes happen because somebody else knows the old one.
    # Leaving their session alive would keep them in the account the change was
    # meant to close, so the change would be cosmetic.
    replay = client.post("/auth/refresh", json={"refresh_token": other_device})
    assert replay.status_code == 401, replay.text


def test_changing_the_password_should_hand_back_no_credentials(client):
    tokens = _signup(client)

    changed = _change(client, tokens["access_token"])

    # 204 and an empty body. An earlier version answered 200 with a replacement
    # token pair so the caller stayed signed in; the client sends them to /login
    # instead, which left that pair with no reader and made it nothing but a
    # live credential in a response body, a devtools panel and any proxy log.
    assert changed.status_code == 204, changed.text
    assert changed.content == b""


def test_changing_one_password_should_not_sign_other_accounts_out(client):
    """The revocation sweep is a bare DELETE over refresh_tokens plus a filter.

    Every other test here has one account, so dropping that filter changes
    nothing any of them can see — and the route would then log the whole
    installation out on every password change. Verified: without the second
    account this file passes with the WHERE clause deleted.
    """
    tokens = _signup(client)
    bystander = client.post(
        "/auth/signup",
        json={
            **SIGNUP_PAYLOAD,
            "email": "bystander@example.com",
            "church": "Other Church",
        },
    )
    assert bystander.status_code == 201, bystander.text

    changed = _change(client, tokens["access_token"])
    assert changed.status_code == 204, changed.text

    survives = client.post(
        "/auth/refresh",
        json={"refresh_token": bystander.json()["tokens"]["refresh_token"]},
    )
    assert survives.status_code == 200, survives.text


def test_the_session_that_authorised_the_change_should_stop_working(client):
    tokens = _signup(client)

    changed = _change(client, tokens["access_token"])
    assert changed.status_code == 204, changed.text

    # "Every session but this one" is not what happens: the caller's own pair
    # goes with the rest, and nothing replaces it. This is the other half of the
    # decision — without it, only "other devices die" is pinned and a route that
    # spared the caller would still be green in the test above.
    replay = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401, replay.text


def test_password_change_burst_past_the_limit_should_return_429(client):
    """The route runs two bcrypt rounds and is the only credential path with no
    per-account counter behind it, so the IP limit is the whole cap.

    Every attempt is refused on purpose: a successful change would move the
    current password out from under the next call and the burst would start
    failing for that reason instead.
    """
    tokens = _signup(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}", **CALLER}
    body = {"current_password": "Wrongpass1", "new_password": NEW_PASSWORD}

    for attempt in range(PASSWORD_CHANGES_PER_MINUTE):
        refused = client.post("/auth/password", json=body, headers=headers)
        assert refused.status_code == 403, f"request {attempt + 1}: {refused.text}"

    blocked = client.post("/auth/password", json=body, headers=headers)

    assert blocked.status_code == 429, blocked.text
