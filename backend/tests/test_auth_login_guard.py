"""Covers the per-account lockout, the defence the address limits cannot give.

The unit tests pass an explicit `now` rather than sleeping, so the fifteen
minute window is exercised in microseconds. The integration test spends real
bcrypt rounds and is the slow one; there is one of it on purpose.
"""

from app import login_guard
from app.login_guard import LOCKOUT_SECONDS, MAX_FAILURES, WINDOW_SECONDS

EMAIL = "target@example.com"

SIGNUP_PAYLOAD = {
    "name": "target",
    "email": EMAIL,
    "password": "Password1",
    "church": "Guard Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def test_failures_below_the_threshold_should_not_lock():
    for i in range(MAX_FAILURES - 1):
        login_guard.record_failure(EMAIL, now=float(i))

    assert login_guard.seconds_until_unlocked(EMAIL, now=float(MAX_FAILURES)) == 0


def test_reaching_the_threshold_should_lock():
    for i in range(MAX_FAILURES):
        login_guard.record_failure(EMAIL, now=float(i))

    assert login_guard.seconds_until_unlocked(EMAIL, now=float(MAX_FAILURES)) > 0


def test_the_lock_should_lift_a_fixed_interval_after_it_was_applied():
    """The clock starts at the failure that tripped it, not at the first one."""
    for i in range(MAX_FAILURES):
        login_guard.record_failure(EMAIL, now=float(i))

    applied_at = float(MAX_FAILURES - 1)
    assert login_guard.seconds_until_unlocked(EMAIL, now=applied_at + LOCKOUT_SECONDS - 1) > 0
    assert login_guard.seconds_until_unlocked(EMAIL, now=applied_at + LOCKOUT_SECONDS + 1) == 0


def test_failures_older_than_the_window_should_not_count_toward_the_lock():
    """The tally slides: nine failures now and one a fortnight later is not ten."""
    for i in range(MAX_FAILURES - 1):
        login_guard.record_failure(EMAIL, now=float(i))

    login_guard.record_failure(EMAIL, now=float(WINDOW_SECONDS + 1))

    assert login_guard.seconds_until_unlocked(EMAIL, now=float(WINDOW_SECONDS + 1)) == 0


def test_a_spray_of_new_addresses_should_not_evict_an_active_lock():
    """The LRU cap must not become a way to unlock an account.

    Tallies are one request each and get evicted; a lock costs MAX_FAILURES
    failed requests and must not. Held in the same LRU map, a locked entry was
    in fact the *first* thing evicted — nothing refreshes its recency, because
    the lock check does not touch it and record_failure is skipped while
    locked — so MAX_TRACKED_ACCOUNTS junk addresses silently lifted the lock.
    """
    for i in range(MAX_FAILURES):
        login_guard.record_failure(EMAIL, now=float(i))
    assert login_guard.seconds_until_unlocked(EMAIL, now=float(MAX_FAILURES)) > 0

    for i in range(login_guard.MAX_TRACKED_ACCOUNTS + 50):
        login_guard.record_failure(f"spray{i}@example.com", now=float(MAX_FAILURES))

    assert login_guard.seconds_until_unlocked(EMAIL, now=float(MAX_FAILURES)) > 0


def test_a_successful_sign_in_should_clear_the_tally():
    for i in range(MAX_FAILURES - 1):
        login_guard.record_failure(EMAIL, now=float(i))

    login_guard.clear(EMAIL)

    login_guard.record_failure(EMAIL, now=float(MAX_FAILURES))
    assert login_guard.seconds_until_unlocked(EMAIL, now=float(MAX_FAILURES)) == 0


def test_locking_one_address_should_leave_others_alone():
    for i in range(MAX_FAILURES):
        login_guard.record_failure(EMAIL, now=float(i))

    assert login_guard.seconds_until_unlocked("bystander@example.com", now=0.0) == 0


def test_tracking_should_stay_bounded_under_a_spray_of_new_addresses():
    """The key is attacker-controlled, so the map needs a ceiling."""
    for i in range(login_guard.MAX_TRACKED_ACCOUNTS + 50):
        login_guard.record_failure(f"spray{i}@example.com", now=0.0)

    assert login_guard.tracked_count() == login_guard.MAX_TRACKED_ACCOUNTS


def test_a_distributed_spray_should_lock_the_address_it_targets(client):
    """Each attempt arrives from a different address, so every one of them is
    the first in its own rate-limit bucket and the IP limit never fires. The
    account counter is the only thing standing in the way."""
    signup = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert signup.status_code == 201, signup.text

    for i in range(MAX_FAILURES):
        attempt = client.post(
            "/auth/login",
            json={"email": EMAIL, "password": "WrongPass1"},
            headers={"X-Real-IP": f"203.0.113.{i}"},
        )
        assert attempt.status_code == 401, f"attempt {i}: {attempt.text}"

    # The right password, from yet another address, and still refused: a
    # lockout a correct guess can walk through would not be one.
    response = client.post(
        "/auth/login",
        json={"email": EMAIL, "password": SIGNUP_PAYLOAD["password"]},
        headers={"X-Real-IP": "203.0.113.200"},
    )

    assert response.status_code == 429, response.text
    assert int(response.headers["Retry-After"]) > 0
    assert "시도" in response.json()["detail"]


def test_an_unregistered_address_should_lock_the_same_way(client):
    """Otherwise the lockout answers a question 401 refuses to: whether the
    address is registered at all."""
    for i in range(MAX_FAILURES):
        client.post(
            "/auth/login",
            json={"email": "ghost@example.com", "password": "WrongPass1"},
            headers={"X-Real-IP": f"203.0.113.{i}"},
        )

    assert login_guard.seconds_until_unlocked("ghost@example.com") > 0
