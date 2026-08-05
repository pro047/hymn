"""Pins login behaviour. M0 wrote this to fix the pre-M4 shape; M4 rewrote the
assertions that were pinning bugs on purpose (see the timing test at the end)."""

import time

from app import login_guard
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


def test_a_legacy_account_whose_password_holds_a_newline_should_still_sign_in(client, db_session):
    """Signup blocks control characters; login must not.

    Accounts registered through the API before that rule existed still hold
    such a password, and rejecting it here would turn "wrong password" into
    "malformed request" and lock them out for good — there is no reset flow.
    The account has to be built directly: signup now refuses this password.
    """
    legacy_password = "Passwo\nrd1"
    church = Church(name="Legacy Church", address="Seoul")
    db_session.add(church)
    db_session.flush()
    db_session.add(
        User(
            church_id=church.id,
            email="legacy@example.com",
            name="legacy",
            password_hash=hash_password(legacy_password),
            role="member",
        )
    )
    db_session.commit()

    response = _login(client, email="legacy@example.com", password=legacy_password)

    assert response.status_code == 200, response.text


def test_a_legacy_newline_password_typed_without_the_newline_should_not_sign_in(client, db_session):
    """The flip side, and the reason such an account is stranded on the web:
    <input type="password"> strips CR/LF, so the form can only ever send this."""
    church = Church(name="Legacy Church", address="Seoul")
    db_session.add(church)
    db_session.flush()
    db_session.add(
        User(
            church_id=church.id,
            email="legacy@example.com",
            name="legacy",
            password_hash=hash_password("Passwo\nrd1"),
            role="member",
        )
    )
    db_session.commit()

    response = _login(client, email="legacy@example.com", password="Password1")

    assert response.status_code == 401, response.text


def test_login_with_a_nul_byte_in_the_password_should_return_401(client):
    """bcrypt refuses NUL bytes and passlib raises rather than answering False.

    Verifying against the decoy hash made every login reach that call, so an
    unauthenticated caller could turn /auth/login into a 500 at will. hash()
    refuses NUL too, so no account can hold such a password and 401 is the
    honest answer.
    """
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    on_the_account = _login(client, password="Passw\x00rd1")
    on_an_unknown_address = _login(client, email="nobody@example.com", password="Passw\x00rd1")

    assert on_the_account.status_code == 401, on_the_account.text
    assert on_an_unknown_address.status_code == 401, on_an_unknown_address.text


def test_login_with_a_nul_byte_in_the_password_should_still_count_toward_the_lockout(client):
    """The escaping exception skipped the tally, so these attempts were free."""
    _login(client, email="nul@example.com", password="Passw\x00rd1")

    assert login_guard.seconds_until_unlocked("nul@example.com") == 0
    assert login_guard.tracked_count() == 1


def test_login_with_malformed_email_should_return_422(client):
    response = _login(client, email="a@b")

    assert response.status_code == 422


def test_login_for_unknown_email_should_cost_about_as_much_as_a_wrong_password(
    client, production_bcrypt_cost
):
    """Closes the user-enumeration oracle M0 pinned in its opposite form.

    A missing account used to skip bcrypt, so the miss path answered in about no
    time and response time alone told a caller whether an address was
    registered. authenticate() now verifies against a decoy hash instead.

    The rest of the suite runs bcrypt at four rounds; this one puts the real
    cost back, because what it asserts is a ratio between two durations and at
    four rounds both sides are under a millisecond of hashing wrapped in far
    more than that of HTTP and SQL.
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
