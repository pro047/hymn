"""Pins the refresh_tokens sweep: what it deletes, what it must not, and that a
failing sweep cannot take a login down with it.

The rule under test is a single one — delete WHERE expires_at <= now - margin —
and the whole safety argument for it rests on two things being true at once:

* a row old enough to sweep belongs to a JWT that already fails its `exp`
  check, so nothing can reach the replay-detection path for it any more
  (test_an_expired_refresh_jwt_should_be_refused_before_the_database_is_read);
* a row young enough that replay detection still matters is never old enough to
  match the rule (the two preservation tests, and the past-grace one).

Break either and the sweep starts eating evidence: a replayed token would come
back as a plain 401 with no family revocation, which is indistinguishable from
an ordinary expiry in the logs and in the response. That is why the past-grace
case asserts the *winner* token dies too rather than merely that the replay is
refused — refusal alone passes even when detection has been silently disabled.

Rows are aged directly instead of sleeping, and the extra rows in the bulk
tests are inserted straight through the model: they only exist to be counted,
and minting them through the HTTP paths would drag bcrypt and the rate limiter
into a test about a DELETE.
"""

import logging
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.models import RefreshToken, naive_utc_now
from app.services import token_sweep
from app.services.auth import REFRESH_REUSE_GRACE_SECONDS, _encode_token, decode_token
from app.services.token_sweep import (
    REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS,
    REFRESH_SWEEP_INTERVAL_SECONDS,
    maybe_sweep_expired_refresh_tokens,
    sweep_expired_refresh_tokens,
)

SIGNUP_PAYLOAD = {
    "name": "sweeper",
    "email": "sweeper@example.com",
    "password": "Password1",
    "church": "Sweep Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

OTHER_PAYLOAD = {
    **SIGNUP_PAYLOAD,
    "name": "other sweeper",
    "email": "other-sweeper@example.com",
    "church": "Other Sweep Church",
}


def _now() -> datetime:
    """The same clock the column and the sweep use, not a fourth copy of it."""
    return naive_utc_now()


def _signup(client, payload: dict = SIGNUP_PAYLOAD) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def _jti(refresh_token: str) -> str:
    return decode_token(refresh_token)["jti"]


def _user_id(access_token: str) -> str:
    return decode_token(access_token)["sub"]


def _row_exists(db_session, jti: str) -> bool:
    """Reads the id as a column, never session.get.

    The sweep deletes in bulk, which leaves the identity map holding whatever
    instance signup put there; get() would answer from that stale copy and
    report a deleted row as still present.
    """
    return db_session.query(RefreshToken.id).filter(RefreshToken.id == jti).scalar() is not None


def _set_expiry(db_session, jti: str, expires_at: datetime) -> None:
    db_session.query(RefreshToken).filter(RefreshToken.id == jti).update(
        {RefreshToken.expires_at: expires_at}, synchronize_session=False
    )
    db_session.flush()


def _plant(db_session, user_id: str, expires_at: datetime, count: int = 1) -> list[str]:
    """Inserts `count` refresh rows with a chosen expiry. Returns their ids."""
    ids = [str(uuid.uuid4()) for _ in range(count)]
    for row_id in ids:
        db_session.add(RefreshToken(id=row_id, user_id=user_id, expires_at=expires_at))
    db_session.flush()
    return ids


def _age_rotation_past_grace(db_session, jti: str) -> None:
    row = db_session.get(RefreshToken, jti)
    row.rotated_at = row.rotated_at - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS + 60)
    db_session.flush()


def test_the_sweep_constants_should_stay_at_their_reviewed_values():
    """The three numbers are the whole configuration surface, so they are pinned
    as literals rather than read back from the module.

    Each one carries an argument that stops holding if it moves. The margin
    covers the sub-second skew between expires_at and the JWT `exp` claim plus
    host clock adjustment; shrink it towards zero and the sweep starts reaping
    rows whose JWT may still decode. The interval is what keeps the DELETE off
    the vast majority of requests. The row cap is what bounds the lock and WAL
    footprint of a DELETE running inside a user's login.
    """
    assert token_sweep.REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS == 60 * 60
    assert token_sweep.REFRESH_SWEEP_INTERVAL_SECONDS == 60 * 60 * 6
    assert token_sweep.REFRESH_SWEEP_MAX_ROWS == 1000


@pytest.mark.parametrize(
    ("seconds_past_the_margin", "expected_deleted"),
    [
        pytest.param(-60, 0, id="inside-the-margin-is-kept"),
        # Straddling the boundary by a minute passes either way, so the exact
        # hit is the only case that tells <= apart from <.
        pytest.param(0, 1, id="exactly-on-the-cutoff-is-deleted"),
        pytest.param(60, 1, id="past-the-margin-is-deleted"),
    ],
)
def test_the_margin_should_decide_a_row_by_its_expiry(
    client, db_session, seconds_past_the_margin, expected_deleted
):
    tokens = _signup(client)
    jti = _jti(tokens["refresh_token"])
    now = _now()
    _set_expiry(
        db_session,
        jti,
        now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + seconds_past_the_margin),
    )

    deleted = sweep_expired_refresh_tokens(db_session, now=now)

    assert deleted == expected_deleted
    assert _row_exists(db_session, jti) is (expected_deleted == 0)


def test_sweeping_an_expired_rotated_row_should_delete_it_and_keep_the_winner(client, db_session):
    """A rotated row is not special to the rule — only its expires_at is read.

    The winner assertion is the point: the rule must not be reachable by "this
    jti was rotated", or a live session would go with the spent row it replaced.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]
    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    winner_jti = _jti(rotated.json()["refresh_token"])

    now = _now()
    _set_expiry(db_session, _jti(original), now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60))

    deleted = sweep_expired_refresh_tokens(db_session, now=now)

    assert deleted == 1
    assert not _row_exists(db_session, _jti(original))
    assert _row_exists(db_session, winner_jti)


def test_sweeping_should_leave_an_active_token_usable(client, db_session):
    """The preservation case the brief named. An untouched signup row is 30 days
    from expiry, so it is never a candidate — and the token still refreshes.
    """
    tokens = _signup(client)
    jti = _jti(tokens["refresh_token"])

    deleted = sweep_expired_refresh_tokens(db_session, now=_now())

    assert deleted == 0
    assert _row_exists(db_session, jti)
    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text


def test_sweeping_should_leave_a_row_rotated_inside_the_grace_window(client, db_session):
    """The second preservation case the brief named.

    A row rotated seconds ago keeps the expires_at it was issued with, so the
    rule cannot see it. The behaviour that matters is what survives: the
    original is refused as a racing tab (401) while the token that won the
    rotation still works — no family revocation.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]
    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    winner = rotated.json()["refresh_token"]

    deleted = sweep_expired_refresh_tokens(db_session, now=_now())

    assert deleted == 0
    rotated_at = (
        db_session.query(RefreshToken.rotated_at).filter(RefreshToken.id == _jti(original)).scalar()
    )
    assert rotated_at is not None

    assert client.post("/auth/refresh", json={"refresh_token": original}).status_code == 401
    survives = client.post("/auth/refresh", json={"refresh_token": winner})
    assert survives.status_code == 200, survives.text


def test_sweeping_should_not_disarm_replay_detection_for_an_unexpired_rotated_row(client, db_session):
    """The design's rejected alternative — deleting on rotated_at age — dies here.

    This row was rotated long ago but its JWT is still valid for weeks, so
    presenting it is the theft signal rotation exists to catch. A sweep keyed on
    rotated_at would have removed the row, and the replay would come back as a
    bare 401 with the thief's session left alive. The winner's 401 is what
    proves revoke_all_sessions actually fired; asserting only the replay's 401
    would pass with detection switched off.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]
    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    winner = rotated.json()["refresh_token"]
    _age_rotation_past_grace(db_session, _jti(original))

    deleted = sweep_expired_refresh_tokens(db_session, now=_now())

    assert deleted == 0
    assert _row_exists(db_session, _jti(original))
    assert client.post("/auth/refresh", json={"refresh_token": original}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": winner}).status_code == 401


def test_the_sweep_should_not_be_scoped_to_one_user(client, db_session):
    """One pass clears every account's expired rows.

    Every other delete in this service keys on a jti or a user_id, so a sweep
    that inherited that habit would leave the table growing for everyone but
    whoever happened to log in.
    """
    first = _signup(client)
    second = _signup(client, OTHER_PAYLOAD)
    now = _now()
    stale = now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60)
    planted = _plant(db_session, _user_id(first["access_token"]), stale)
    planted += _plant(db_session, _user_id(second["access_token"]), stale)

    deleted = sweep_expired_refresh_tokens(db_session, now=now)

    assert deleted == 2
    assert [_row_exists(db_session, row_id) for row_id in planted] == [False, False]
    assert _row_exists(db_session, _jti(first["refresh_token"]))
    assert _row_exists(db_session, _jti(second["refresh_token"]))


def test_the_row_limit_should_cap_one_pass_and_leave_the_rest(client, db_session):
    """The cap is what keeps a large backlog from turning one login into a long
    DELETE. It has to bound the pass without widening it — the live row must
    still be out of scope.
    """
    tokens = _signup(client)
    now = _now()
    planted = _plant(
        db_session,
        _user_id(tokens["access_token"]),
        now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60),
        count=5,
    )

    deleted = sweep_expired_refresh_tokens(db_session, now=now, limit=3)

    assert deleted == 3
    survivors = [row_id for row_id in planted if _row_exists(db_session, row_id)]
    assert len(survivors) == 2
    assert _row_exists(db_session, _jti(tokens["refresh_token"]))


def test_the_sweep_should_not_commit_on_its_own(client, db_session):
    """The caller owns the transaction boundary, same contract as
    revoke_all_refresh_tokens.

    If the sweep committed, the savepoint that protects token issuance would be
    protecting nothing: a caller that later rolled back would find the deletes
    already durable, and worse, a mid-request commit would make every write the
    caller had staged so far durable with it.
    """
    tokens = _signup(client)
    now = _now()
    planted = _plant(
        db_session,
        _user_id(tokens["access_token"]),
        now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60),
    )
    db_session.commit()

    assert sweep_expired_refresh_tokens(db_session, now=now) == 1
    assert not _row_exists(db_session, planted[0])

    db_session.rollback()

    assert _row_exists(db_session, planted[0])


def test_the_throttle_should_block_a_second_sweep_inside_the_interval(client, db_session):
    tokens = _signup(client)
    user_id = _user_id(tokens["access_token"])
    stale = _now() - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60)
    # Signup issued a token, which already claimed the throttle stamp off the
    # real monotonic clock. Clearing it is what standing six hours later looks
    # like from here; without it the injected clock reads as being in the past.
    token_sweep.reset()
    first_batch = _plant(db_session, user_id, stale)

    assert maybe_sweep_expired_refresh_tokens(db_session, clock=100.0) == 1
    assert token_sweep.last_swept_at() == 100.0
    assert not _row_exists(db_session, first_batch[0])

    second_batch = _plant(db_session, user_id, stale)
    blocked = maybe_sweep_expired_refresh_tokens(db_session, clock=100.0 + REFRESH_SWEEP_INTERVAL_SECONDS - 1)

    # The row is the assertion, not the return value: a sweep that ran and
    # deleted nothing would also return 0, and only the surviving row shows the
    # DELETE never went out.
    assert blocked == 0
    assert _row_exists(db_session, second_batch[0])


def test_the_sweep_should_run_again_once_the_interval_has_passed(client, db_session):
    tokens = _signup(client)
    user_id = _user_id(tokens["access_token"])
    stale = _now() - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60)
    token_sweep.reset()
    _plant(db_session, user_id, stale)

    assert maybe_sweep_expired_refresh_tokens(db_session, clock=100.0) == 1

    later_batch = _plant(db_session, user_id, stale)
    ran = maybe_sweep_expired_refresh_tokens(db_session, clock=100.0 + REFRESH_SWEEP_INTERVAL_SECONDS + 1)

    assert ran == 1
    assert not _row_exists(db_session, later_batch[0])


def test_logging_in_should_carry_the_sweep_with_it(client, db_session):
    """The whole scheduling story is this one piggyback: no cron, no lifespan
    hook, nothing that stops running when deploys go quiet. If issue_token_bundle
    ever stops calling the sweep, nothing else in the system will.
    """
    tokens = _signup(client)
    stale = _now() - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60)
    planted = _plant(db_session, _user_id(tokens["access_token"]), stale)
    # Signup's own token issuance already claimed the throttle stamp off the
    # real monotonic clock. Clearing it is what standing six hours later looks
    # like from here.
    token_sweep.reset()

    login = client.post(
        "/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )

    assert login.status_code == 200, login.text
    assert not _row_exists(db_session, planted[0])


def test_a_failing_sweep_should_not_take_the_signup_down_with_it(
    client, db_session, monkeypatch, caplog
):
    """The savepoint is load-bearing. In PostgreSQL one failed statement aborts
    the whole transaction, so without it a broken sweep would roll back the
    account, the church and the refresh token the request had just created — a
    cleanup bug would present as signup being completely down.

    Asserting the row exists, not just the 201: the response could be built and
    still be lost if the commit went nowhere. The signup's own INSERTs are
    already flushed by the time the sweep runs — begin_nested() flushes before
    it emits the SAVEPOINT — so surviving the rollback is the thing being
    checked, not merely that they were still pending.
    """
    calls = []

    def _explode(session, **_kwargs):
        # A statement the database actually rejects, not a bare `raise`. Only a
        # real failure puts the transaction into the aborted state the savepoint
        # exists to contain; raising in Python leaves it healthy, and this test
        # then passes with begin_nested() deleted — which is exactly how it read
        # before, pinning nothing.
        calls.append(True)
        session.execute(text("DELETE FROM no_such_table"))

    monkeypatch.setattr(token_sweep, "sweep_expired_refresh_tokens", _explode)

    with caplog.at_level(logging.WARNING, logger="app.services.token_sweep"):
        response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert calls, "the sweep never ran, so this proves nothing about failing sweeps"
    assert response.status_code == 201, response.text
    assert _row_exists(db_session, _jti(response.json()["tokens"]["refresh_token"]))
    # A sweep that dies every interval otherwise returns the same 0 as one with
    # nothing to do, and the table quietly grows as if the feature were absent.
    assert "refresh token sweep failed" in caplog.text


def test_an_expired_refresh_jwt_should_be_refused_before_the_database_is_read(client, db_session):
    """The premise the sweep's safety argument rests on.

    This jti was rotated long ago, so presenting a *valid* JWT for it revokes
    every session — that is the existing past-grace test. Present the same jti
    inside a JWT whose exp has passed and decode fails first, so the row is
    never read and nothing is revoked. The second session still refreshing is
    what proves the detection path was never reached.

    That is exactly the state a swept row leaves behind, which is why deleting
    it costs no detection: by the time the sweep can touch a row, every JWT
    naming it has been dying at this same first check for at least an hour.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]
    claims = decode_token(original)
    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    _age_rotation_past_grace(db_session, claims["jti"])

    other_session = client.post(
        "/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )
    assert other_session.status_code == 200, other_session.text
    other_refresh = other_session.json()["tokens"]["refresh_token"]

    expired = _encode_token(
        {
            "sub": claims["sub"],
            "church_id": claims["church_id"],
            "type": "refresh",
            "jti": claims["jti"],
        },
        expires_in=-3600,
    )

    replay = client.post("/auth/refresh", json={"refresh_token": expired})
    assert replay.status_code == 401, replay.text

    survives = client.post("/auth/refresh", json={"refresh_token": other_refresh})
    assert survives.status_code == 200, survives.text


def test_a_sweep_that_deleted_rows_should_report_the_count_in_the_log(client, db_session, caplog):
    """This log line is the only place the table's size ever becomes visible.

    Nobody has measured how many rows production carries — there is no admin
    query for it and no metric. The count printed here is what answers that
    afterwards, so it is part of the feature rather than decoration, and the
    number is asserted rather than merely that something was logged.

    Pinned at WARNING, not INFO: nothing in this app configures logging, so the
    root logger sits where uvicorn leaves it and an INFO line never reaches the
    container log — utils/email.py carries the same note for the same reason.
    Reading it at INFO here would pass while production saw nothing.
    """
    tokens = _signup(client)
    stale = _now() - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60)
    _plant(db_session, _user_id(tokens["access_token"]), stale, count=2)
    token_sweep.reset()

    with caplog.at_level(logging.WARNING, logger="app.services.token_sweep"):
        assert maybe_sweep_expired_refresh_tokens(db_session, clock=100.0) == 2

    assert "swept 2 expired refresh tokens" in caplog.text


def test_a_sweep_that_deleted_nothing_should_stay_quiet(client, db_session, caplog):
    """Four "swept 0" lines a day is how a log stops being read."""
    _signup(client)
    token_sweep.reset()

    with caplog.at_level(logging.WARNING, logger="app.services.token_sweep"):
        assert maybe_sweep_expired_refresh_tokens(db_session, clock=100.0) == 0

    assert "swept" not in caplog.text


@pytest.mark.parametrize("limit", [0, 1])
def test_the_limit_should_be_honoured_at_its_smallest_values(client, db_session, limit):
    """limit=0 is the degenerate case a caller could reach by computing a budget.

    It has to mean "delete nothing", not "no limit" — a LIMIT 0 that got dropped
    or coerced away would take the whole backlog in one statement, which is the
    exact footprint the cap exists to prevent.
    """
    tokens = _signup(client)
    now = _now()
    planted = _plant(
        db_session,
        _user_id(tokens["access_token"]),
        now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS + 60),
        count=2,
    )

    deleted = sweep_expired_refresh_tokens(db_session, now=now, limit=limit)

    assert deleted == limit
    assert len([row_id for row_id in planted if _row_exists(db_session, row_id)]) == 2 - limit
