"""Pins what a member may do inside their own church: read the scores, nothing else.

Only the leader uploads, places, edits and arranges; a member account exists so
that a person belongs to a church and can open its scores on the tablet. Every
data route is therefore either leader-only or explicitly open to members, and
the first test fails for a route that was added without choosing.

Cross-church access is test_church_isolation's subject. This file stays inside
one church.
"""

import io
from datetime import timedelta

import pytest
from PIL import Image

import test_church_isolation as isolation
from app.deps import get_object_reader
from app.main import app
from song_helpers import file_usage

THIS_WEEK = isolation.THIS_WEEK
WEEK = isolation.WEEK
NEXT_WEEK = (THIS_WEEK + timedelta(days=7)).isoformat()

LEADER_ONLY_DETAIL = {"detail": "인도자만 할 수 있는 작업입니다."}

LEADER_PAYLOAD = {
    "name": "leader",
    "email": "leader@example.com",
    "password": "Password1",
    "church": "Leader Only Church",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

SONG_TITLE = "Amazing Grace"

# Open to a member: the two reads the tablet app shows a congregation its
# scores with. Everything else under LEADER_ONLY is refused with 403.
MEMBER_ALLOWED = {
    ("GET", "/scores"),
    ("GET", "/scores/{score_id}"),
}


class Church:
    """One church: its leader, one member, and one song on this week."""

    def __init__(self, client):
        founded = client.post("/auth/signup", json=LEADER_PAYLOAD)
        assert founded.status_code == 201, founded.text
        joined = client.post(
            "/auth/signup",
            json={**LEADER_PAYLOAD, "email": "member@example.com", "join_code": founded.json()["church"]["code"]},
        )
        assert joined.status_code == 201, joined.text
        assert joined.json()["user"]["role"] == "member"

        self.client = client
        self.church_id = founded.json()["user"]["church_id"]
        self.leader = self._headers(founded.json())
        self.member = self._headers(joined.json())
        placed = file_usage(client, self.leader, title=SONG_TITLE, week=THIS_WEEK).json()
        self.song_id = placed["song_id"]
        self.score_id = placed["score_id"]

    @staticmethod
    def _headers(account: dict) -> dict:
        return {"Authorization": f"Bearer {account['tokens']['access_token']}"}

    def snapshot(self) -> dict:
        """Everything a refused write could have changed, read as the leader."""
        client, leader = self.client, self.leader
        score = client.get(f"/scores/{self.score_id}", headers=leader).json()
        edit = client.get(f"/scores/{self.score_id}/edit", headers=leader).json()
        return {
            # Stored fields only. The presigned URLs beside them are signed
            # with the second they were issued in, so two reads a moment apart
            # differ without anything having changed.
            "score": {key: score[key] for key in ("id", "title", "week_of", "file_uri", "song_id")},
            "edit": {key: edit[key] for key in ("edited_file_uri", "edit_doc")},
            "songs": [
                (song["song_id"], song["title"], song["use_count"])
                for song in client.get("/songs", headers=leader).json()
            ],
            "this_week": self._placed(WEEK),
            "next_week": self._placed(NEXT_WEEK),
        }

    def _placed(self, week: str) -> list[str]:
        conti = self.client.get(f"/weeks/{week}/conti", headers=self.leader).json()
        return [item["score_id"] for page in conti["pages"] for item in page]


# Each request is one the leader may make, so that a 403 can only be about the
# caller's role and never about the body or the id.
LEADER_ONLY = {
    ("POST", "/scores/{score_id}/file"): lambda c: (
        f"/scores/{c.score_id}/file",
        {"json": {"filename": "rescan.png", "content_type": "image/png"}},
    ),
    ("GET", "/scores/{score_id}/edit"): lambda c: (f"/scores/{c.score_id}/edit", {}),
    ("POST", "/scores/{score_id}/edited-file"): lambda c: (f"/scores/{c.score_id}/edited-file", {}),
    ("PUT", "/scores/{score_id}/edit"): lambda c: (
        f"/scores/{c.score_id}/edit",
        {"json": {"edited_file_uri": f"scores/{c.church_id}/edited.png", "edit_doc": {}}},
    ),
    ("DELETE", "/scores/{score_id}/edit"): lambda c: (f"/scores/{c.score_id}/edit", {}),
    ("PATCH", "/scores/{score_id}"): lambda c: (f"/scores/{c.score_id}", {"json": {"title": "renamed"}}),
    ("DELETE", "/scores/{score_id}"): lambda c: (f"/scores/{c.score_id}", {}),
    ("GET", "/songs"): lambda c: ("/songs", {}),
    ("POST", "/songs"): lambda c: (
        "/songs",
        {"json": {"title": "A New Song", "filename": "score.png", "content_type": "image/png"}},
    ),
    ("POST", "/songs/{song_id}/usages"): lambda c: (f"/songs/{c.song_id}/usages", {"json": {"week_of": NEXT_WEEK}}),
    ("GET", "/weeks/{week_of}/pdf"): lambda c: (f"/weeks/{WEEK}/pdf", {}),
    ("GET", "/weeks/{week_of}/conti"): lambda c: (f"/weeks/{WEEK}/conti", {}),
    ("PATCH", "/weeks/{week_of}/conti/order"): lambda c: (
        f"/weeks/{WEEK}/conti/order",
        {"json": {"items": [{"score_id": c.score_id}]}},
    ),
}


@pytest.fixture()
def sheet_reader():
    """The PDF route reads the song's file; give it one instead of S3."""
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, "PNG")
    app.dependency_overrides[get_object_reader] = lambda: lambda key: buffer.getvalue()
    yield
    app.dependency_overrides.pop(get_object_reader, None)


def test_every_data_route_should_be_leader_only_or_explicitly_open_to_members():
    # Arrange
    data_routes = isolation._served_routes() - isolation.NON_DATA_ROUTES
    classified = set(LEADER_ONLY) | MEMBER_ALLOWED

    # Assert
    assert data_routes == classified, (
        f"data routes with no decision about members: {sorted(data_routes - classified)}; "
        f"decisions for routes the app does not serve: {sorted(classified - data_routes)}"
    )


@pytest.mark.parametrize("route", sorted(LEADER_ONLY), ids=lambda route: f"{route[0]} {route[1]}")
def test_a_member_should_be_refused_on_a_leader_only_route(client, sheet_reader, route):
    # Arrange
    church = Church(client)
    method = route[0]
    path, kwargs = LEADER_ONLY[route](church)
    before = church.snapshot()

    # Act
    refused = client.request(method, path, headers=church.member, **kwargs)

    # Assert — refused for the role, and nothing moved.
    assert refused.status_code == 403, refused.text
    assert refused.json() == LEADER_ONLY_DETAIL
    assert church.snapshot() == before

    # Assert — the same request is the leader's to make, so the 403 above was
    # about who asked and not about what was asked.
    allowed = client.request(method, path, headers=church.leader, **kwargs)
    assert allowed.status_code < 400, allowed.text


def test_a_member_should_still_list_the_churchs_scores(client):
    # Arrange
    church = Church(client)

    # Act
    response = client.get("/scores", headers=church.member)

    # Assert
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [church.score_id]


def test_a_member_should_still_open_one_of_the_churchs_scores(client):
    # Arrange
    church = Church(client)

    # Act
    response = client.get(f"/scores/{church.score_id}", headers=church.member)

    # Assert
    assert response.status_code == 200, response.text
    assert response.json()["title"] == SONG_TITLE
