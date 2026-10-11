"""Pins what GET /scores answers, by what the caller sent with it.

Three cases, and the split between the first and the third is the point.

No Authorization header at all: the filed scores of the one church named by
ANONYMOUS_SCORES_CHURCH_ID, and no other church's. The tablets in the field
send no header and have no login screen, and they all belong to that church,
so this answer is a contract with an app that cannot be updated in place.
With the variable unset the answer is 503 rather than every church's list:
a deployment that forgot the line must fail where a smoke test sees it.

A valid access token: the caller's own church and nothing else, in the same
order and the same shape.

A header that is present but does not hold up: 401, never the public answer.
Falling back would hand a leader whose token had just expired every other
church's list, and the web client would never refresh because it never saw
the 401 that triggers it.
"""

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt

from app.deps import SESSION_EXPIRED_MESSAGE
from app.models import Score, User
from app.services.auth import JWT_ALGORITHM, _encode_token, decode_token
from song_helpers import file_usage


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()

CHURCH_A_PAYLOAD = {
    "name": "leader a",
    "email": "leader-a@example.com",
    "password": "Password1",
    "church": "Scope Church A",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

CHURCH_B_PAYLOAD = {
    **CHURCH_A_PAYLOAD,
    "name": "leader b",
    "email": "leader-b@example.com",
    "church": "Scope Church B",
}

# The contract shared with hymn_app. A key added here reaches tablets that
# cannot be updated on a deploy; a key removed breaks the ones already out.
SCORE_KEYS = {
    "id",
    "church_id",
    "week_of",
    "title",
    "file_url",
    "file_uri",
    "download_url",
    "created_at",
    "song_id",
}

EXPIRED_BODY = {"detail": SESSION_EXPIRED_MESSAGE}

ANONYMOUS_CHURCH_ENV = "ANONYMOUS_SCORES_CHURCH_ID"


def _serve_anonymous(monkeypatch, account: dict) -> None:
    """Names the account's church as the one header-less callers are shown."""
    monkeypatch.setenv(ANONYMOUS_CHURCH_ENV, account["user"]["church_id"])


def _signup(client, payload: dict) -> dict:
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _headers(account: dict) -> dict:
    return _bearer(account["tokens"]["access_token"])


def _place(client, account: dict, title: str) -> str:
    return file_usage(client, _headers(account), title=title, week=THIS_WEEK).json()["score_id"]


def _stamp(db_session, score_id: str, minute: int) -> None:
    """Fixes created_at, so the order asserted is one this file chose.

    Left to the clock, rows land in insertion order and "sorted by created_at"
    cannot be told apart from "returned as inserted".
    """
    db_session.query(Score).filter(Score.id == score_id).update(
        {"created_at": datetime(2026, 1, 1, 9, minute)}
    )
    db_session.expire_all()


def _two_churches_with_one_score_each(client) -> tuple[dict, dict, str, str]:
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    a_score = _place(client, a, "Amazing Grace")
    b_score = _place(client, b, "How Great Thou Art")
    return a, b, a_score, b_score


# --- no header: the app's contract ---------------------------------------


def test_listing_without_a_header_should_return_only_the_named_churchs_scores_oldest_first(
    client, db_session, monkeypatch
):
    # Arrange — stamped against insertion order, so only a sort produces this,
    # with one of B's between A's in time.
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    late = _place(client, a, "Amazing Grace")
    early = _place(client, a, "Be Thou My Vision")
    foreign = _place(client, b, "How Great Thou Art")
    _stamp(db_session, late, minute=30)
    _stamp(db_session, foreign, minute=20)
    _stamp(db_session, early, minute=10)
    _serve_anonymous(monkeypatch, a)

    # Act
    response = client.get("/scores")

    # Assert
    assert response.status_code == 200, response.text
    listed = response.json()
    assert [item["id"] for item in listed] == [early, late]
    assert {item["church_id"] for item in listed} == {a["user"]["church_id"]}
    assert [item["title"] for item in listed] == ["Be Thou My Vision", "Amazing Grace"]
    for item in listed:
        assert set(item) == SCORE_KEYS
        assert item["week_of"] == THIS_WEEK.isoformat()
        assert item["file_uri"].startswith(f"scores/{item['church_id']}/")


def test_listing_without_a_header_should_follow_the_named_church_not_the_first_one(client, monkeypatch):
    # Arrange — the other direction: a filter pinned to whichever church
    # signed up first would pass the test above and fail here.
    a, b, a_score, b_score = _two_churches_with_one_score_each(client)
    _serve_anonymous(monkeypatch, b)

    # Act
    response = client.get("/scores")

    # Assert
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [b_score]


def test_listing_without_a_header_should_return_an_empty_list_when_the_named_church_has_no_scores(
    client, monkeypatch
):
    # Arrange — only the other church has filed anything.
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    _place(client, a, "Amazing Grace")
    _serve_anonymous(monkeypatch, b)

    # Act
    response = client.get("/scores")

    # Assert
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_listing_without_a_header_should_return_503_when_no_church_is_named(client, monkeypatch, value):
    # Arrange — never the old answer: with no church named, every church's
    # list is the one thing this must not fall back to.
    _two_churches_with_one_score_each(client)
    if value is None:
        monkeypatch.delenv(ANONYMOUS_CHURCH_ENV, raising=False)
    else:
        monkeypatch.setenv(ANONYMOUS_CHURCH_ENV, value)

    # Act
    response = client.get("/scores")

    # Assert
    assert response.status_code == 503, response.text
    assert "id" not in response.text


def test_listing_with_a_token_should_not_depend_on_the_named_church(client, monkeypatch):
    # Arrange — the variable names A; B signs in.
    a, b, _, b_score = _two_churches_with_one_score_each(client)
    _serve_anonymous(monkeypatch, a)

    # Act
    named = client.get("/scores", headers=_headers(b))
    monkeypatch.delenv(ANONYMOUS_CHURCH_ENV)
    unnamed = client.get("/scores", headers=_headers(b))

    # Assert
    assert [item["id"] for item in named.json()] == [b_score]
    assert unnamed.status_code == 200, unnamed.text
    assert [item["id"] for item in unnamed.json()] == [b_score]


# --- a valid token: the caller's church only -----------------------------


def test_listing_with_a_token_should_return_only_that_churchs_scores(client):
    # Arrange
    a, b, a_score, b_score = _two_churches_with_one_score_each(client)
    a_second = _place(client, a, "Be Thou My Vision")

    # Act
    as_a = client.get("/scores", headers=_headers(a))
    as_b = client.get("/scores", headers=_headers(b))

    # Assert — both directions: a filter that only hid B from A would pass half.
    assert as_a.status_code == 200, as_a.text
    assert as_b.status_code == 200, as_b.text
    assert sorted(item["id"] for item in as_a.json()) == sorted([a_score, a_second])
    assert {item["church_id"] for item in as_a.json()} == {a["user"]["church_id"]}
    assert [item["id"] for item in as_b.json()] == [b_score]
    assert {item["church_id"] for item in as_b.json()} == {b["user"]["church_id"]}


def test_listing_with_a_token_should_return_an_empty_list_for_a_church_with_no_scores(client):
    # Arrange — only the other church has filed anything.
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    _place(client, a, "Amazing Grace")

    # Act
    response = client.get("/scores", headers=_headers(b))

    # Assert
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_listing_with_a_token_should_keep_the_created_at_order(client, db_session, monkeypatch):
    # Arrange — three of A's, stamped out of insertion order, with one of B's
    # between them in time.
    a = _signup(client, CHURCH_A_PAYLOAD)
    b = _signup(client, CHURCH_B_PAYLOAD)
    first = _place(client, a, "Amazing Grace")
    second = _place(client, a, "Be Thou My Vision")
    third = _place(client, a, "Come Thou Fount")
    foreign = _place(client, b, "How Great Thou Art")
    _stamp(db_session, first, minute=40)
    _stamp(db_session, second, minute=10)
    _stamp(db_session, foreign, minute=20)
    _stamp(db_session, third, minute=30)
    _serve_anonymous(monkeypatch, a)

    # Act
    scoped = client.get("/scores", headers=_headers(a))
    public = client.get("/scores")

    # Assert
    assert [item["id"] for item in scoped.json()] == [second, third, first]
    a_church = a["user"]["church_id"]
    assert [item["id"] for item in scoped.json()] == [
        item["id"] for item in public.json() if item["church_id"] == a_church
    ]


def test_listing_with_a_token_should_answer_in_the_same_shape_as_without(client, monkeypatch):
    # Arrange
    a, _, a_score, _ = _two_churches_with_one_score_each(client)
    _serve_anonymous(monkeypatch, a)

    # Act
    scoped = client.get("/scores", headers=_headers(a)).json()
    public = client.get("/scores").json()

    # Assert — the same row, field for field. download_url is signed per
    # request, so it is compared for presence rather than for equality.
    mine = next(item for item in scoped if item["id"] == a_score)
    same_row = next(item for item in public if item["id"] == a_score)
    assert set(mine) == SCORE_KEYS
    assert mine["download_url"] is not None
    assert same_row["download_url"] is not None
    for key in SCORE_KEYS - {"download_url"}:
        assert mine[key] == same_row[key], key


def test_listing_with_a_token_should_still_leave_out_scores_with_no_week(client, db_session):
    # Arrange — a legacy library draft: a score row filed on no Sunday.
    a = _signup(client, CHURCH_A_PAYLOAD)
    kept = _place(client, a, "Amazing Grace")
    draft = _place(client, a, "Be Thou My Vision")
    db_session.query(Score).filter(Score.id == draft).update({"week_of": None})
    db_session.expire_all()

    # Act
    response = client.get("/scores", headers=_headers(a))

    # Assert
    assert [item["id"] for item in response.json()] == [kept]


# --- a header that does not hold up: 401, never the public list ----------


def test_listing_with_a_malformed_token_should_return_401(client):
    # Arrange
    _two_churches_with_one_score_each(client)

    # Act
    response = client.get("/scores", headers=_bearer("not-a-jwt"))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_an_expired_token_should_return_401(client):
    # Arrange — the caller's own claims, re-signed with an exp already past.
    a, *_ = _two_churches_with_one_score_each(client)
    claims = decode_token(a["tokens"]["access_token"])
    expired = _encode_token(
        {key: claims[key] for key in ("sub", "church_id", "role", "type", "tv")},
        expires_in=-60,
    )

    # Act
    response = client.get("/scores", headers=_bearer(expired))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_token_signed_by_another_secret_should_return_401(client):
    # Arrange
    a, *_ = _two_churches_with_one_score_each(client)
    claims = decode_token(a["tokens"]["access_token"])
    forged = jwt.encode(claims, "not-the-server-secret", algorithm=JWT_ALGORITHM)

    # Act
    response = client.get("/scores", headers=_bearer(forged))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_non_bearer_scheme_should_return_401(client):
    # Arrange
    _two_churches_with_one_score_each(client)

    # Act
    response = client.get("/scores", headers={"Authorization": "Token abc"})

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_token_from_before_a_version_bump_should_return_401(client, db_session):
    # Arrange — what a password change does to every token already issued.
    a, *_ = _two_churches_with_one_score_each(client)
    db_session.query(User).filter(User.id == a["user"]["id"]).update(
        {"token_version": User.token_version + 1}
    )
    db_session.expire_all()

    # Act
    response = client.get("/scores", headers=_headers(a))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_refresh_token_should_return_401(client):
    # Arrange
    a, *_ = _two_churches_with_one_score_each(client)

    # Act
    response = client.get("/scores", headers=_bearer(a["tokens"]["refresh_token"]))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_token_for_a_user_that_does_not_exist_should_return_401(client):
    # Arrange — well signed and unexpired, naming nobody.
    a, *_ = _two_churches_with_one_score_each(client)
    orphan = _encode_token(
        {"sub": str(uuid4()), "church_id": a["user"]["church_id"], "role": "leader", "type": "access", "tv": 0},
        expires_in=600,
    )

    # Act
    response = client.get("/scores", headers=_bearer(orphan))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_a_token_that_names_no_user_should_return_401(client):
    # Arrange — no sub claim at all.
    a, *_ = _two_churches_with_one_score_each(client)
    nameless = _encode_token(
        {"church_id": a["user"]["church_id"], "role": "leader", "type": "access", "tv": 0},
        expires_in=600,
    )

    # Act
    response = client.get("/scores", headers=_bearer(nameless))

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY


def test_listing_with_an_empty_authorization_header_should_return_401(client):
    """An empty header was still sent. Only its absence means anonymous."""
    # Arrange
    _two_churches_with_one_score_each(client)

    # Act
    response = client.get("/scores", headers={"Authorization": ""})

    # Assert
    assert response.status_code == 401, response.text
    assert response.json() == EXPIRED_BODY
