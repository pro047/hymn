from datetime import timedelta

from app.models import RefreshToken
from app.services.auth import REFRESH_REUSE_GRACE_SECONDS, decode_token

SIGNUP_PAYLOAD = {
    "name": "tester",
    "email": "tester@example.com",
    "password": "Password1",
    "church": "Test Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}


def _signup(client) -> dict:
    response = client.post("/auth/signup", json=SIGNUP_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["tokens"]


def _bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def test_refresh_with_a_garbage_token_should_answer_in_korean(client):
    """The client renders `detail` verbatim for a non-422 body, so an English
    string here is an English string on the user's screen.

    The literal is spelled out rather than imported from routes.auth. Comparing
    the response against the very constant that produced it passes whatever the
    constant says, including an English rewrite — which is the one thing this
    test exists to catch.
    """
    response = client.post("/auth/refresh", json={"refresh_token": "x" * 40})

    assert response.status_code == 401
    assert response.json()["detail"] == "로그인이 만료되었습니다. 다시 로그인해 주세요."


def test_refresh_returns_rotated_token_pair(client):
    tokens = _signup(client)

    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != tokens["refresh_token"]


def test_refresh_token_cannot_be_reused_after_rotation(client):
    """Immediate reuse is the grace path: refused, but not treated as a replay.

    The second presentation lands within the grace window, so it is read as two
    tabs racing the same rotation rather than a theft. It is refused (401), and
    crucially the token that won the rotation still works — no family
    revocation. The past-the-window case is the test below.
    """
    tokens = _signup(client)

    first = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200, first.text

    reuse = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401

    rotated = first.json()["refresh_token"]
    second = client.post("/auth/refresh", json={"refresh_token": rotated})
    assert second.status_code == 200, second.text


def test_replaying_a_spent_token_past_the_grace_window_should_revoke_the_family(client, db_session):
    """A superseded token presented long after it was rotated is a replay.

    That is the theft signal rotation exists to catch: the real client rotated
    the token, then someone presents the old one. Detecting it does nothing
    unless it acts — the earlier version raised 401 and left the thief's own
    freshly-rotated family alive. This revokes everything.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]

    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    winner = rotated.json()["refresh_token"]

    # Age the rotation stamp past the grace window. In production the victim
    # presents the spent token minutes to hours later; here it is aged directly
    # so the test does not sleep. The client fixture runs on this same session,
    # so the write is visible to the next request without a commit.
    jti = decode_token(original)["jti"]
    row = db_session.get(RefreshToken, jti)
    row.rotated_at = row.rotated_at - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS + 60)
    db_session.flush()

    replay = client.post("/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401, replay.text

    # The winner's token is dead too: a detected replay ends every session, not
    # just the one that was replayed. The real user re-logs in; a thief holding
    # the rotated family is evicted with them.
    after = client.post("/auth/refresh", json={"refresh_token": winner})
    assert after.status_code == 401, after.text


def test_a_detected_replay_should_also_kill_outstanding_access_tokens(client, db_session):
    """Revocation on replay bumps token_version, so stolen access tokens die too.

    A refresh replay means the session is compromised; leaving the matching
    access token alive for its remaining hour would hand the thief exactly the
    window the revocation is meant to close.
    """
    tokens = _signup(client)
    original = tokens["refresh_token"]
    access = tokens["access_token"]

    rotated = client.post("/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200, rotated.text
    # The signup's access token is stale after one rotation reissued the pair,
    # but token_version has not changed, so it still authenticates.
    assert client.get("/auth/me", headers=_bearer(access)).status_code == 200

    jti = decode_token(original)["jti"]
    row = db_session.get(RefreshToken, jti)
    row.rotated_at = row.rotated_at - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS + 60)
    db_session.flush()

    assert client.post("/auth/refresh", json={"refresh_token": original}).status_code == 401

    # The bump retires it: 401, not the 200 it gave a line ago.
    assert client.get("/auth/me", headers=_bearer(access)).status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = _signup(client)

    logout = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout.status_code == 204

    response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_logout_should_delete_the_row_not_merely_stamp_it(client, db_session):
    """Logout removes the row; rotation is what stamps rotated_at.

    The distinction has teeth. A stamped-but-kept row is a spent token that,
    replayed past the grace window, would be read as a theft and revoke the
    user's other sessions — so a sign-out on one device could later knock out
    the rest. Logout carries no such signal, so its row simply goes.

    Read with a column query, not session.get: the row was added to this
    session at signup and a bulk delete leaves the identity map holding a stale
    instance, which get would hand back as though nothing was deleted.
    """
    tokens = _signup(client)
    jti = decode_token(tokens["refresh_token"])["jti"]

    client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    present = db_session.query(RefreshToken.id).filter(RefreshToken.id == jti).scalar()
    assert present is None


def test_login_issued_refresh_token_is_valid(client):
    _signup(client)

    login = client.post(
        "/auth/login",
        json={"email": SIGNUP_PAYLOAD["email"], "password": SIGNUP_PAYLOAD["password"]},
    )
    assert login.status_code == 200, login.text
    refresh_token = login.json()["tokens"]["refresh_token"]

    response = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200, response.text
