"""Pins signup behaviour.

M2 moved every input rule out of the router's manual `if` checks and into
SignupRequest, so what used to answer 400 with a bare string now answers 422 with
Pydantic's item array. Tests that still carry a `# M3:` comment mark rules that are
knowingly wrong today and change in a later milestone.
"""


def _detail_for(response, field: str) -> dict:
    """The 422 item raised for one field. `loc` is ["body", <field>]."""
    items = response.json()["detail"]
    matches = [item for item in items if item["loc"][-1] == field]
    assert matches, f"no 422 item for {field!r}: {items}"
    return matches[0]

SIGNUP_PAYLOAD = {
    "name": "tester",
    "email": "tester@example.com",
    "password": "Password1",
    "church": "Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _payload(**overrides) -> dict:
    return {**SIGNUP_PAYLOAD, **overrides}


def test_signup_with_new_church_should_create_member_and_return_201(client):
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == SIGNUP_PAYLOAD["email"]
    # Signup never elects a leader today, so a brand-new church has none.
    assert body["user"]["role"] == "member"
    assert body["church"]["name"] == SIGNUP_PAYLOAD["church"]
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]


def test_signup_with_uppercase_email_should_store_it_lowercased(client):
    response = client.post("/auth/signup", json=_payload(email="Tester@Example.com"))

    assert response.status_code == 201, response.text
    assert response.json()["user"]["email"] == "tester@example.com"


def test_signup_with_existing_church_name_should_reuse_that_church(client):
    first = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert first.status_code == 201, first.text

    second = client.post("/auth/signup", json=_payload(email="other@example.com"))

    assert second.status_code == 201, second.text
    # Exact name match is the only gate today: no invite code, no approval.
    assert second.json()["church"]["id"] == first.json()["church"]["id"]


def test_signup_with_duplicate_email_should_return_409(client):
    first = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert first.status_code == 201, first.text

    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["detail"] == "이미 사용 중인 이메일입니다."


def test_signup_without_agreed_terms_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(agreed_terms=False))

    assert response.status_code == 422
    # The Korean wording must survive the move into the schema: the frontend
    # strips pydantic's "Value error, " prefix and renders the rest verbatim.
    assert "약관 동의가 필요합니다." in _detail_for(response, "agreed_terms")["msg"]


def test_signup_password_without_uppercase_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(password="password1"))

    assert response.status_code == 422
    item = _detail_for(response, "password")
    assert item["type"] == "value_error"
    assert "영문 대문자와 소문자" in item["msg"]


def test_signup_password_without_lowercase_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(password="PASSWORD1"))

    assert response.status_code == 422
    assert "영문 대문자와 소문자" in _detail_for(response, "password")["msg"]


def test_signup_password_shorter_than_8_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(password="Pass1"))

    assert response.status_code == 422
    # Length stays a Field constraint, so the frontend keeps its own Korean
    # wording for it instead of echoing the server.
    assert _detail_for(response, "password")["type"] == "string_too_short"


def test_signup_password_longer_than_16_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(password="PasswordPassword1"))

    assert response.status_code == 422
    item = _detail_for(response, "password")
    assert item["type"] == "string_too_long"
    assert item["ctx"]["max_length"] == 16


def test_signup_with_malformed_email_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(email="a@b"))

    # EmailStr rejects a dotless domain that the browser's type="email" lets through.
    assert response.status_code == 422


def test_signup_422_should_not_echo_the_submitted_password(client):
    rejected = "password1"

    response = client.post("/auth/signup", json=_payload(password=rejected))

    # Pydantic puts the rejected value in `input`. For a near-miss password that
    # is a live credential the user is about to retry, and it would end up in
    # devtools, HAR exports and any proxy that logs response bodies.
    assert response.status_code == 422
    assert rejected not in response.text
    assert "input" not in _detail_for(response, "password")


def test_signup_422_should_still_carry_the_context_the_client_renders(client):
    response = client.post("/auth/signup", json=_payload(phone="010"))

    # Stripping `input` must not take `ctx` with it — the frontend reads
    # ctx.min_length to word its own message.
    assert _detail_for(response, "phone")["ctx"]["min_length"] == 8


def test_signup_with_trailing_hyphen_domain_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(email="a@example-.com"))

    # The frontend's zod pattern lets this through, so it is the one input that
    # reaches the server invalid. Pinned in
    # frontend/src/lib/validation/auth-schema.test.ts as a known divergence.
    assert response.status_code == 422
    assert _detail_for(response, "email")["type"] == "value_error"


def test_signup_with_phone_shorter_than_8_should_return_422(client):
    response = client.post("/auth/signup", json=_payload(phone="010"))

    # The frontend has no phone rule at all, so this 422 is user-reachable today.
    assert response.status_code == 422


def test_check_email_for_unused_address_should_report_available(client):
    response = client.get("/auth/check-email", params={"email": SIGNUP_PAYLOAD["email"]})

    assert response.status_code == 200, response.text
    assert response.json() == {"available": True}


def test_check_email_for_registered_address_should_report_unavailable(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    response = client.get("/auth/check-email", params={"email": SIGNUP_PAYLOAD["email"]})

    assert response.status_code == 200, response.text
    assert response.json() == {"available": False}


def test_check_email_with_malformed_address_should_return_422(client):
    response = client.get("/auth/check-email", params={"email": "not-an-email"})

    # EmailStr rejects before the lookup runs, so a malformed address costs no
    # query and reveals nothing. `loc` is ["query", "email"] here, not ["body", …].
    assert response.status_code == 422
    assert _detail_for(response, "email")["loc"][0] == "query"


def test_me_with_access_token_should_return_session(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text
    access_token = signup.json()["tokens"]["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == SIGNUP_PAYLOAD["email"]
    assert body["church"]["name"] == SIGNUP_PAYLOAD["church"]
    assert body["issued_at"]


def test_me_without_authorization_header_should_return_401(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_with_refresh_token_should_return_401(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text
    refresh_token = signup.json()["tokens"]["refresh_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})

    assert response.status_code == 401
