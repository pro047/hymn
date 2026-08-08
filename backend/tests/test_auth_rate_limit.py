"""Pins the auth throttle.

/auth/check-email answers without authentication, so wiring it into the signup
form hands anyone an oracle for "is this address registered here". These tests
exist to keep the throttle from being weakened or bypassed by accident.

The limits themselves live in app/rate_limit.py; the numbers are read from there
rather than repeated, so raising a limit does not silently turn a test into a
no-op. Only the *shape* of the behaviour is asserted here.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.rate_limit import (
    CHECK_EMAIL_LIMIT,
    LOGIN_LIMIT,
    RATE_LIMIT_MESSAGE,
    REFRESH_LIMIT,
    SIGNUP_LIMIT,
)

CHECK_EMAIL_PER_MINUTE = int(CHECK_EMAIL_LIMIT.split("/")[0])
LOGIN_PER_MINUTE = int(LOGIN_LIMIT.split("/")[0])
SIGNUP_PER_MINUTE = int(SIGNUP_LIMIT.split("/")[0])
REFRESH_PER_MINUTE = int(REFRESH_LIMIT.split("/")[0])

CALLER = {"X-Real-IP": "203.0.113.10"}
OTHER_CALLER = {"X-Real-IP": "203.0.113.99"}


def _check_email(client, headers: dict, email: str = "someone@example.com"):
    return client.get("/auth/check-email", params={"email": email}, headers=headers)


def test_check_email_burst_past_the_limit_should_return_429(client):
    for attempt in range(CHECK_EMAIL_PER_MINUTE):
        allowed = _check_email(client, CALLER)
        assert allowed.status_code == 200, f"request {attempt + 1} was rejected: {allowed.text}"

    blocked = _check_email(client, CALLER)

    assert blocked.status_code == 429


def test_two_client_ips_should_not_share_a_check_email_limit(client):
    """The regression test for the reverse-proxy trap.

    nginx proxies to 127.0.0.1, so slowapi's default key — the socket peer —
    is identical for every caller in production. Under that key one visitor's
    burst locks out the whole site, and this test is what fails if the key ever
    goes back to it.
    """
    for _ in range(CHECK_EMAIL_PER_MINUTE + 1):
        _check_email(client, CALLER)

    response = _check_email(client, OTHER_CALLER)

    assert response.status_code == 200, response.text


def test_a_spoofed_forwarded_for_should_not_buy_a_fresh_limit(client):
    """X-Forwarded-For is caller-controlled; only X-Real-IP is set by nginx."""
    for _ in range(CHECK_EMAIL_PER_MINUTE + 1):
        _check_email(client, CALLER)

    response = _check_email(client, {**CALLER, "X-Forwarded-For": "198.51.100.7"})

    assert response.status_code == 429


def test_check_email_and_login_should_not_share_a_bucket(client):
    """A limit is per endpoint, so probing addresses cannot lock a user out."""
    for _ in range(CHECK_EMAIL_PER_MINUTE + 1):
        _check_email(client, CALLER)

    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "Password1"},
        headers=CALLER,
    )

    # 401 rather than 429: the request was let through and simply found no user.
    assert response.status_code == 401, response.text


def test_login_burst_past_the_limit_should_return_429(client):
    """Every attempt uses a different address, and that is load-bearing.

    login_guard locks an account after MAX_FAILURES failures and that happens
    to be the same number as LOGIN_LIMIT. Aim the burst at one address and the
    429 comes from the lockout whether or not @limiter.limit(LOGIN_LIMIT) is
    still on the route — deleting the decorator left this file entirely green.
    Spreading the attempts across addresses keeps the per-IP limit the only
    thing that can answer, and the message assertion says which one did.
    """
    password = {"password": "Password1"}
    for index in range(LOGIN_PER_MINUTE):
        client.post("/auth/login", json={"email": f"burst{index}@example.com", **password}, headers=CALLER)

    blocked = client.post("/auth/login", json={"email": "burst-last@example.com", **password}, headers=CALLER)

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": RATE_LIMIT_MESSAGE}, "429 came from the lockout, not the IP limit"


def test_signup_burst_past_the_limit_should_return_429(client):
    """Signup is the most expensive route (bcrypt + two INSERTs), so it is capped.

    This also pins the decorator order: @router.post has to stay outside
    @limiter.limit, or the router registers the undecorated function and the cap
    disappears with no error, no warning and no response-header difference.
    """
    payload = {
        "name": "tester",
        "email": "tester@example.com",
        "password": "Password1",
        "church": "Test Church",
        "church_address": "Seoul",
        "phone": "01012345678",
        "agreed_terms": True,
    }
    for index in range(SIGNUP_PER_MINUTE):
        # Each call needs a fresh address, otherwise the second one 409s and the
        # test would pass for the wrong reason. A fresh church name for the same
        # reason: reusing one makes every call after the first a 403 for want of
        # that church's invite code, and the cap would then be measured against
        # requests that never reached the expensive part of the route.
        client.post(
            "/auth/signup",
            json={**payload, "email": f"t{index}@example.com", "church": f"Test Church {index}"},
            headers=CALLER,
        )

    blocked = client.post("/auth/signup", json={**payload, "email": "last@example.com"}, headers=CALLER)

    assert blocked.status_code == 429


def test_refresh_burst_past_the_limit_should_return_429(client):
    """/auth/refresh is unauthenticated and writes twice on success, so it is capped too."""
    # RefreshRequest sets min_length=20; a shorter token is rejected as 422 before
    # the limiter ever counts it, and this test would then never see a 429.
    payload = {"refresh_token": "x" * 40}
    for _ in range(REFRESH_PER_MINUTE):
        client.post("/auth/refresh", json=payload, headers=CALLER)

    blocked = client.post("/auth/refresh", json=payload, headers=CALLER)

    assert blocked.status_code == 429


def test_x_real_ip_from_a_non_loopback_peer_should_be_ignored(client):
    """Only the local proxy may name the caller.

    A request that reaches the port without passing through nginx controls its own
    headers, so honouring X-Real-IP there would let it pick a fresh bucket per
    request and make every limit a no-op.
    """
    for _ in range(CHECK_EMAIL_PER_MINUTE + 1):
        _check_email(client, CALLER)

    with TestClient(app, client=("203.0.113.77", 40000)) as direct:
        # Same header the proxied caller used; it must not inherit that bucket,
        # and more importantly it must not be able to choose one.
        first = _check_email(direct, CALLER)
        for _ in range(CHECK_EMAIL_PER_MINUTE):
            _check_email(direct, {"X-Real-IP": "198.51.100.1"})
        blocked = _check_email(direct, {"X-Real-IP": "198.51.100.2"})

    assert first.status_code == 200, first.text
    assert blocked.status_code == 429


def test_rate_limited_response_should_carry_a_korean_detail_message(client):
    """The client reads `detail` and nothing else (frontend/src/lib/api-error.ts).

    slowapi's own handler answers `{"error": "10 per 1 minute"}`, which that
    reader cannot see — it would fall back to a generic sentence. This asserts
    the replacement handler is still registered.
    """
    for _ in range(CHECK_EMAIL_PER_MINUTE):
        _check_email(client, CALLER)

    blocked = _check_email(client, CALLER)

    assert blocked.status_code == 429
    assert blocked.json() == {"detail": RATE_LIMIT_MESSAGE}


def test_rate_limited_response_should_carry_retry_after(client):
    """Without it a client has no basis for backoff and just retries immediately."""
    for _ in range(CHECK_EMAIL_PER_MINUTE):
        _check_email(client, CALLER)

    blocked = _check_email(client, CALLER)

    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


def test_a_proxied_request_without_x_real_ip_should_warn_once(client, caplog):
    """A proxy that stops sending the header collapses everyone into one bucket.

    That is invisible from the outside — requests simply start sharing a limit —
    so the fallback says so in the log instead of failing silently.
    """
    import app.rate_limit as rate_limit_module

    rate_limit_module._warned_missing_real_ip = False

    with caplog.at_level("WARNING", logger="app.rate_limit"):
        client.get("/auth/check-email", params={"email": "a@example.com"})
        client.get("/auth/check-email", params={"email": "b@example.com"})

    warnings = [record for record in caplog.records if "X-Real-IP" in record.message]
    assert len(warnings) == 1
