"""Pins login behaviour. M0 wrote this to fix the pre-M4 shape; M4 rewrote the
assertions that were pinning bugs on purpose (see the timing test at the end)."""

import time

from app.models import Church, User
from app.routes.auth import INVALID_CREDENTIALS_MESSAGE
from app.services.auth import hash_password

SIGNUP_PAYLOAD = {
    "name": "tester",
    "email": "tester@example.com",
    "password": "Password1",
    "church": "Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _login(client, **overrides):
    body = {"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]}
    return client.post("/auth/login", json={**body, **overrides})


def test_login_with_valid_credentials_should_return_token_pair(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    response = _login(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tokens"]["access_token"]
    assert body["tokens"]["token_type"] == "bearer"
    assert body["user"]["email"] == SIGNUP_PAYLOAD["email"]
    assert body["church"]["name"] == SIGNUP_PAYLOAD["church"]


def test_login_with_uppercase_email_should_match_the_stored_account(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    response = _login(client, email="Tester@Example.com")

    assert response.status_code == 200, response.text


def test_login_with_unknown_email_should_return_401(client):
    response = _login(client, email="nobody@example.com")

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE


def test_login_with_wrong_password_should_return_401(client):
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    response = _login(client, password="WrongPass1")

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE


def test_login_for_user_without_password_hash_should_return_401(client, db_session):
    church = Church(name="Legacy Church", address="Seoul")
    db_session.add(church)
    db_session.flush()
    db_session.add(
        User(
            church_id=church.id,
            email="legacy@example.com",
            name="legacy",
            password_hash=None,
            role="member",
        )
    )
    db_session.commit()

    response = _login(client, email="legacy@example.com")

    assert response.status_code == 401


def test_login_password_longer_than_16_should_reach_the_hash_check(client, db_session):
    """LoginRequest keeps max_length=128 on purpose: accounts predating the 16-char
    policy must still be able to sign in. M2 must not tighten this alongside signup."""
    long_password = "PasswordPassword1"
    church = Church(name="Legacy Church", address="Seoul")
    db_session.add(church)
    db_session.flush()
    db_session.add(
        User(
            church_id=church.id,
            email="legacy@example.com",
            name="legacy",
            password_hash=hash_password(long_password),
            role="member",
        )
    )
    db_session.commit()

    response = _login(client, email="legacy@example.com", password=long_password)

    assert response.status_code == 200, response.text


def test_login_with_a_newline_in_the_password_should_not_be_rejected_by_validation(client):
    """Signup blocks control characters; login must not.

    Accounts registered through the API before that rule existed still hold such
    a password, and a 422 here would turn "wrong password" into "malformed
    request" for them. The gate belongs on the way in only.
    """
    response = _login(client, password="Passwo\nrd1")

    assert response.status_code == 401, response.text


def test_login_with_malformed_email_should_return_422(client):
    response = _login(client, email="a@b")

    assert response.status_code == 422


def test_login_for_unknown_email_should_cost_about_as_much_as_a_wrong_password(client):
    """Closes the user-enumeration oracle M0 pinned in its opposite form.

    A missing account used to skip bcrypt, so the miss path answered in about no
    time and response time alone told a caller whether an address was
    registered. authenticate() now verifies against a decoy hash instead.
    """
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    started = time.perf_counter()
    _login(client, email="nobody@example.com")
    unknown_email_seconds = time.perf_counter() - started

    started = time.perf_counter()
    _login(client, password="WrongPass1")
    wrong_password_seconds = time.perf_counter() - started

    # Lower bound only, and a wide one. What has to hold is that the miss path
    # still pays for a bcrypt round; how closely the two match depends on how
    # loaded the machine is. Drop the decoy and this ratio falls to ~0.01.
    assert unknown_email_seconds > wrong_password_seconds * 0.5
