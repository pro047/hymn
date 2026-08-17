"""Pins /auth/password-reset: the one recovery path that needs no old password.

The account is proved by possession of a mailed link instead, which puts three
things under test that /auth/password never had to answer for: the request must
say the same thing about an address that exists and one that does not, the link
must be usable exactly once and only for half an hour, and the reset must end
every session rather than preserve the caller's — the person resetting may be
locking somebody else out.

What is deliberately *not* here: the password rules themselves. The confirm body
uses the same NewPassword as signup, so test_auth_signup.py owns those cases; the
one 422 below exists only to prove the type is shared and has not been forked.
"""

import hashlib
import logging
import re

import pytest

from app.main import app
from app.models import PasswordResetToken
from app.rate_limit import PASSWORD_RESET_REQUEST_LIMIT
from app.utils.email import get_email_sender

RESET_REQUESTS_PER_HOUR = int(PASSWORD_RESET_REQUEST_LIMIT.split("/")[0])

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

CALLER = {"X-Real-IP": "203.0.113.20"}

# The mailed link is `<base>?token=<urlsafe>`; token_urlsafe emits A-Za-z0-9-_.
TOKEN_IN_LINK = re.compile(r"[?&]token=([A-Za-z0-9_-]+)")


class _Recorder:
    """A transport that keeps the mail instead of sending it."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class _BrokenSender:
    def send(self, message):
        raise RuntimeError("SES said no")


@pytest.fixture()
def outbox():
    """Swaps the email transport out the way the session is swapped out.

    Overriding the dependency rather than monkeypatching a module function keeps
    the route's own wiring under test: if the route stopped scheduling the send,
    or scheduled it with the wrong address, this fixture would still see it.
    """
    recorder = _Recorder()
    app.dependency_overrides[get_email_sender] = lambda: recorder
    yield recorder.sent
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture()
def broken_outbox():
    app.dependency_overrides[get_email_sender] = _BrokenSender
    yield
    app.dependency_overrides.pop(get_email_sender, None)


def _signup(client, **overrides) -> dict:
    response = client.post("/auth/signup", json={**SIGNUP_PAYLOAD, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def _login(client, password: str, email: str = SIGNUP_PAYLOAD["email"]):
    return client.post("/auth/login", json={"email": email, "password": password})


def _request_reset(client, email: str = SIGNUP_PAYLOAD["email"], **kwargs):
    return client.post("/auth/password-reset/request", json={"email": email}, **kwargs)


def _confirm(client, token: str, new_password: str = NEW_PASSWORD):
    return client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": new_password},
    )


def _token_from(messages) -> str:
    assert len(messages) == 1, messages
    found = TOKEN_IN_LINK.search(messages[0].body)
    assert found, messages[0].body
    return found.group(1)


def _mailed_token(client, outbox) -> str:
    assert _request_reset(client).status_code == 202
    return _token_from(outbox)


def test_requesting_a_reset_for_an_unknown_address_should_return_202_and_send_nothing(
    client, outbox, db_session
):
    _signup(client)

    response = _request_reset(client, email="nobody@example.com")

    # 202 for an address with no account, because any other answer here is a
    # free membership check for anyone who can POST.
    assert response.status_code == 202, response.text
    assert outbox == []
    assert db_session.query(PasswordResetToken).count() == 0


def test_the_two_requests_should_be_indistinguishable_from_the_response(client, outbox):
    _signup(client)

    known = _request_reset(client)
    unknown = _request_reset(client, email="nobody@example.com")

    # Status and body both, not just the status: a difference in either is the
    # oracle. Empty bodies are what makes them the same, which is why the route
    # answers 202 with no payload rather than an "email sent" object.
    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content == b""


def test_requesting_a_reset_should_mail_a_link_that_carries_the_token(client, outbox):
    _signup(client)

    response = _request_reset(client)

    assert response.status_code == 202, response.text
    assert len(outbox) == 1
    message = outbox[0]
    assert message.to == SIGNUP_PAYLOAD["email"]
    # A full URL, not a bare token: the console adapter's log is how dev
    # completes the round trip, and the mail is how a user does.
    assert TOKEN_IN_LINK.search(message.body), message.body


def test_the_database_should_hold_only_a_hash_of_the_mailed_token(
    client, outbox, db_session
):
    _signup(client)

    token = _mailed_token(client, outbox)

    rows = db_session.query(PasswordResetToken).all()
    assert len(rows) == 1
    # Both halves matter. The first says the plaintext is not in the table; the
    # second says the stored value is the hash *of this token* and not some
    # unrelated string that happens not to equal it — a mutation that stored a
    # constant would pass the first assertion alone.
    assert rows[0].token_hash != token
    assert rows[0].token_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_a_second_request_should_invalidate_the_first_link(client, outbox, db_session):
    _signup(client)
    first = _mailed_token(client, outbox)

    outbox.clear()
    assert _request_reset(client).status_code == 202
    second = _token_from(outbox)

    # Only the newest link may work. A user who requests again usually does so
    # because the first mail went somewhere they no longer trust.
    assert db_session.query(PasswordResetToken).count() == 1
    assert _confirm(client, first).status_code == 401
    assert _confirm(client, second).status_code == 204


def test_confirming_with_the_mailed_token_should_replace_the_password(client, outbox):
    _signup(client)
    token = _mailed_token(client, outbox)

    response = _confirm(client, token)

    assert response.status_code == 204, response.text
    assert _login(client, CURRENT_PASSWORD).status_code == 401
    assert _login(client, NEW_PASSWORD).status_code == 200


def test_confirming_should_hand_back_no_credentials(client, outbox):
    _signup(client)
    token = _mailed_token(client, outbox)

    response = _confirm(client, token)

    # 204, empty. A reset is the recovery path for an account that may be in
    # someone else's hands; handing an unauthenticated caller a live session on
    # the strength of a link in a mailbox is the thing not to do.
    assert response.status_code == 204, response.text
    assert response.content == b""


def test_reusing_a_spent_token_should_return_401(client, outbox):
    _signup(client)
    token = _mailed_token(client, outbox)
    assert _confirm(client, token).status_code == 204

    response = _confirm(client, token, new_password="Thirdpass1")

    assert response.status_code == 401, response.text
    assert "재설정 링크" in response.json()["detail"]
    # And the second attempt changed nothing: the password is still the one the
    # first confirm set.
    assert _login(client, NEW_PASSWORD).status_code == 200
    assert _login(client, "Thirdpass1").status_code == 401


def test_an_expired_token_should_return_401(client, outbox, db_session):
    import datetime as dt

    _signup(client)
    token = _mailed_token(client, outbox)
    row = db_session.query(PasswordResetToken).one()
    # Aged past the TTL rather than waiting it out. The column is naive UTC,
    # which is what the service compares against.
    row.expires_at = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(seconds=1)
    db_session.commit()

    response = _confirm(client, token)

    assert response.status_code == 401, response.text
    assert _login(client, CURRENT_PASSWORD).status_code == 200


def test_an_unknown_token_should_return_401(client):
    _signup(client)

    response = _confirm(client, "not-a-real-reset-token-value")

    assert response.status_code == 401, response.text
    assert _login(client, CURRENT_PASSWORD).status_code == 200


def test_confirming_should_revoke_every_refresh_token(client, outbox):
    other_device = _signup(client)["refresh_token"]
    token = _mailed_token(client, outbox)

    assert _confirm(client, token).status_code == 204

    # The reason to reset is usually that someone else has the old password.
    # A session of theirs left alive would survive the reset meant to end it.
    replay = client.post("/auth/refresh", json={"refresh_token": other_device})
    assert replay.status_code == 401, replay.text


def test_confirming_should_kill_the_access_tokens_already_issued(client, outbox):
    access = _signup(client)["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200
    token = _mailed_token(client, outbox)

    assert _confirm(client, token).status_code == 204

    # Deleting the refresh rows alone leaves a stolen access token good for up
    # to an hour after the reset. token_version is what retires it now.
    after = client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert after.status_code == 401, after.text


def test_resetting_one_password_should_not_touch_another_account(client, outbox):
    """The revocation sweep is a DELETE plus a WHERE, and every other test here
    has one account — dropping the filter would sign the whole installation out
    on every reset and none of them would notice."""
    _signup(client)
    bystander = client.post(
        "/auth/signup",
        json={
            **SIGNUP_PAYLOAD,
            "email": "bystander@example.com",
            "church": "Other Church",
        },
    )
    assert bystander.status_code == 201, bystander.text
    token = _mailed_token(client, outbox)

    assert _confirm(client, token).status_code == 204

    survives = client.post(
        "/auth/refresh",
        json={"refresh_token": bystander.json()["tokens"]["refresh_token"]},
    )
    assert survives.status_code == 200, survives.text
    assert _login(client, CURRENT_PASSWORD, email="bystander@example.com").status_code == 200


def test_a_new_password_breaking_the_signup_rules_should_return_422(client, outbox):
    """One case, and only to prove the gate is signup's and not a second copy.

    If the confirm body ever grew its own password type, this is what fails —
    the account could then be given a password its own signup form refuses.
    """
    _signup(client)
    token = _mailed_token(client, outbox)

    response = _confirm(client, token, new_password="newpassword1")

    assert response.status_code == 422, response.text
    item = next(i for i in response.json()["detail"] if i["loc"][-1] == "new_password")
    assert "영문 대문자와 소문자" in item["msg"]
    # And the link is not spent by a rejected attempt — 422 happens in
    # validation, before the route body runs.
    assert _confirm(client, token).status_code == 204


def test_a_failing_send_should_still_return_202(client, broken_outbox):
    _signup(client)

    response = _request_reset(client)

    # The send runs after the response as a background task, and Starlette
    # propagates what it raises out of the request — uncaught, a bounced mail
    # would turn this 202 into a 500, and only for addresses that exist.
    assert response.status_code == 202, response.text


def test_the_console_sender_should_log_a_usable_link(client, caplog):
    """The default transport, with no override — this is the dev round trip.

    Until SES is wired up this is also what production runs, and it is how the
    dev e2e gets a token at all. If the log stopped carrying the full URL, that
    would break silently everywhere else.

    The level is asserted too. Nothing configures logging in this app, so
    uvicorn leaves the root logger at WARNING: an INFO line here is captured by
    caplog and dropped by the running server, which is how it was found.
    """
    _signup(client)
    caplog.set_level(logging.WARNING, logger="app.utils.email")

    assert _request_reset(client).status_code == 202

    logged = "\n".join(record.getMessage() for record in caplog.records)
    found = TOKEN_IN_LINK.search(logged)
    assert found, logged
    assert _confirm(client, found.group(1)).status_code == 204


def test_reset_request_burst_past_the_limit_should_return_429(client, outbox):
    """Every accepted call mails somebody who did not necessarily ask for it, so
    the limit is a spam bound as much as a throttle."""
    _signup(client)

    for attempt in range(RESET_REQUESTS_PER_HOUR):
        accepted = _request_reset(client, headers=CALLER)
        assert accepted.status_code == 202, f"request {attempt + 1}: {accepted.text}"

    blocked = _request_reset(client, headers=CALLER)

    assert blocked.status_code == 429, blocked.text
    assert len(outbox) == RESET_REQUESTS_PER_HOUR
