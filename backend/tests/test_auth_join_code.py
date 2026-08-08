"""Pins the church invite code: who may join, who may see it, who may rotate it.

Before this, an exact match on the church name was the entire gate — anyone who
knew what a congregation called itself became a member of it, and a member
passes the tenancy check on every score that church owns. Signup input rules
live in test_auth_signup.py; what is here is the gating those rules feed.
"""

SIGNUP_PAYLOAD = {
    "name": "founder",
    "email": "founder@example.com",
    "password": "Password1",
    "church": "Invite Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _payload(**overrides) -> dict:
    return {**SIGNUP_PAYLOAD, **overrides}


def _found_church(client) -> str:
    """Registers the first account of the church and returns its invite code."""
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert response.status_code == 201, response.text
    code = response.json()["church"]["code"]
    assert code, "the founding account must be shown the code it has to hand out"
    return code


def _join(client, code, **overrides):
    return client.post(
        "/auth/signup",
        json=_payload(**{"email": "joiner@example.com", "join_code": code, **overrides}),
    )


def test_signup_founding_a_church_should_be_shown_its_invite_code(client):
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "leader"
    code = body["church"]["code"]
    # 8 characters from an alphabet with no l/1/o/0, because the code is read
    # off one screen and typed into another by a person.
    assert len(code) == 8
    assert set(code) <= set("abcdefghijkmnpqrstuvwxyz23456789")


def test_signup_with_the_right_invite_code_should_join_as_a_member(client):
    code = _found_church(client)

    response = _join(client, code)

    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "member"


def test_signup_into_an_existing_church_without_a_code_should_return_403(client):
    _found_church(client)

    response = client.post("/auth/signup", json=_payload(email="joiner@example.com"))

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "초대 코드가 올바르지 않습니다. 교회 리더에게 확인해 주세요."


def test_signup_into_an_existing_church_with_a_wrong_code_should_return_403(client):
    _found_church(client)

    response = _join(client, "wrongcod")

    assert response.status_code == 403, response.text
    # Same wording as the missing-code case: telling the caller their guess was
    # the right shape narrows the search for them and changes nothing they do.
    assert response.json()["detail"] == "초대 코드가 올바르지 않습니다. 교회 리더에게 확인해 주세요."


def test_signup_with_a_refused_code_should_not_create_the_account(client):
    _found_church(client)

    refused = client.post("/auth/signup", json=_payload(email="joiner@example.com"))
    assert refused.status_code == 403, refused.text

    # A 403 that still registers the account would leave a user with no church
    # to belong to, and would burn the address they wanted.
    available = client.get("/auth/check-email", params={"email": "joiner@example.com"})
    assert available.json() == {"available": True}


def test_signup_with_an_uppercased_invite_code_should_be_accepted(client):
    code = _found_church(client)

    response = _join(client, f"  {code.upper()}  ")

    # The code travels by hand. A phone keyboard capitalising the first letter,
    # or a space picked up while copying, must not read as the wrong code.
    assert response.status_code == 201, response.text


def test_signup_with_an_over_long_invite_code_should_return_422(client):
    _found_church(client)

    response = _join(client, "x" * 17)

    # Bounded at the schema so an unbounded string never reaches the comparison.
    assert response.status_code == 422, response.text


def test_a_member_should_not_be_told_the_invite_code(client):
    code = _found_church(client)
    joined = _join(client, code)
    assert joined.status_code == 201, joined.text

    assert joined.json()["church"]["code"] is None

    session = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {joined.json()['tokens']['access_token']}"},
    )
    # Also null on the session route, which is what the page reloads from: the
    # code lets its holder into the church, so it does not belong in a member's
    # browser storage or in any log of their session response.
    assert session.json()["church"]["code"] is None


def test_a_leader_should_be_told_the_invite_code_on_the_session_route(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    session = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {signup.json()['tokens']['access_token']}"},
    )

    assert session.status_code == 200, session.text
    # The management page reads it from here rather than keeping the signup
    # response around, so a leader who returns tomorrow can still hand it out.
    assert session.json()["church"]["code"] == signup.json()["church"]["code"]


def test_check_church_for_an_unregistered_name_should_report_it_free(client):
    response = client.get("/auth/check-church", params={"name": SIGNUP_PAYLOAD["church"]})

    assert response.status_code == 200, response.text
    assert response.json() == {"exists": False}


def test_check_church_for_a_registered_name_should_report_it_taken_and_nothing_else(client):
    _found_church(client)

    response = client.get("/auth/check-church", params={"name": SIGNUP_PAYLOAD["church"]})

    assert response.status_code == 200, response.text
    # Equality, not a key lookup: this route is unauthenticated, so anything it
    # adds to the body is public. Returning the code here would leave the church
    # open to whoever guessed its name, which is the hole the code closes.
    assert response.json() == {"exists": True}


def test_check_church_should_match_the_name_the_way_signup_stores_it(client):
    _found_church(client)

    response = client.get(
        "/auth/check-church", params={"name": f"  {SIGNUP_PAYLOAD['church']}  "}
    )

    # SignupRequest.church is trimmed before it is stored, so an untrimmed
    # lookup that missed would tell the form to offer to found a church whose
    # name is already taken — and the signup would then fail on 403.
    assert response.json() == {"exists": True}


def test_check_church_with_a_blank_name_should_return_422(client):
    response = client.get("/auth/check-church", params={"name": "   "})

    assert response.status_code == 422, response.text


def test_rotating_the_invite_code_should_retire_the_old_one(client):
    founding = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert founding.status_code == 201, founding.text
    old_code = founding.json()["church"]["code"]
    access = founding.json()["tokens"]["access_token"]

    rotated = client.post(
        "/auth/church/join-code", headers={"Authorization": f"Bearer {access}"}
    )

    assert rotated.status_code == 200, rotated.text
    new_code = rotated.json()["code"]
    assert new_code != old_code

    # Rotation is the entire answer to a leaked code — there is no revocation
    # list — so the old string has to stop working the moment this returns.
    refused = _join(client, old_code)
    assert refused.status_code == 403, refused.text

    accepted = _join(client, new_code)
    assert accepted.status_code == 201, accepted.text


def test_rotating_the_invite_code_without_a_token_should_return_401(client):
    _found_church(client)

    response = client.post("/auth/church/join-code")

    assert response.status_code == 401, response.text


def test_rotating_the_invite_code_as_a_member_should_return_403(client):
    code = _found_church(client)
    joined = _join(client, code)
    assert joined.status_code == 201, joined.text

    response = client.post(
        "/auth/church/join-code",
        headers={"Authorization": f"Bearer {joined.json()['tokens']['access_token']}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "교회 리더만 초대 코드를 관리할 수 있습니다."

    # A refused rotation must not have changed anything: the leader's code has
    # to still be the one the members were given.
    assert _join(client, code, email="third@example.com").status_code == 201
