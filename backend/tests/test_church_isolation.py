"""Every data route, called by a leader of another church.

One church files a song on this week's Sunday; a leader of a second church
then calls each route in the score, song and conti routers with a valid token
of their own. None of them may show, change or confirm the first church's
data.

The table below is keyed by (method, path template) and checked against the
routes the app actually serves. A route added without a row here fails that
check, so a new surface cannot ship without saying what it does for a
stranger.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.main import app
from song_helpers import file_usage


def _this_week_sunday() -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


THIS_WEEK = _this_week_sunday()
WEEK = THIS_WEEK.isoformat()

# Everything the app serves that is not listed here is a data route and needs
# a row in CASES. Naming each exempt route, rather than a prefix or the modules
# that are covered, is what makes the check below fail for a route added under
# a brand-new path and for one added under /auth/ alike: a member list would
# be church data wherever it is mounted.
NON_DATA_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/health/ready"),
    ("GET", "/auth/check-church"),
    ("GET", "/auth/check-email"),
    ("POST", "/auth/church/join-code"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("POST", "/auth/password"),
    ("POST", "/auth/password-reset/confirm"),
    ("POST", "/auth/password-reset/request"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/signup"),
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

OWNER_PAYLOAD = {
    "name": "owner",
    "email": "owner@example.com",
    "password": "Password1",
    "church": "Isolation Church A",
    "church_address": "Seoul",
    "phone": "01012345678",
    "agreed_terms": True,
}

OUTSIDER_PAYLOAD = {
    **OWNER_PAYLOAD,
    "name": "outsider",
    "email": "outsider@example.com",
    "church": "Isolation Church B",
}

SONG_TITLE = "Amazing Grace"

SCORE_NOT_FOUND = {"detail": "악보를 찾을 수 없습니다."}


class World:
    """Church A with one song on this week, and a leader of church B."""

    def __init__(self, client):
        owner = self._signup(client, OWNER_PAYLOAD)
        outsider = self._signup(client, OUTSIDER_PAYLOAD)
        self.client = client
        self.owner = self._headers(owner)
        self.outsider = self._headers(outsider)
        self.owner_church_id = owner["user"]["church_id"]
        self.outsider_church_id = outsider["user"]["church_id"]
        placed = file_usage(client, self.owner, title=SONG_TITLE, week=THIS_WEEK).json()
        self.song_id = placed["song_id"]
        self.score_id = placed["score_id"]
        self.file_uri = client.get(f"/scores/{self.score_id}", headers=self.owner).json()["file_uri"]

    @staticmethod
    def _signup(client, payload: dict) -> dict:
        response = client.post("/auth/signup", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    @staticmethod
    def _headers(account: dict) -> dict:
        return {"Authorization": f"Bearer {account['tokens']['access_token']}"}

    def as_outsider(self, method: str, path: str, **kwargs):
        return self.client.request(method, path, headers=self.outsider, **kwargs)


def _assert_indistinguishable_from_a_missing_score(world: World, method: str, suffix: str = "", **kwargs):
    """404 for A's score, and the very same answer for an id that names nothing.

    A status or wording that differed between the two would tell the caller
    which ids are real.
    """
    real = world.as_outsider(method, f"/scores/{world.score_id}{suffix}", **kwargs)
    missing = world.as_outsider(method, f"/scores/{uuid4()}{suffix}", **kwargs)

    assert real.status_code == 404, real.text
    assert real.json() == SCORE_NOT_FOUND
    assert (missing.status_code, missing.json()) == (real.status_code, real.json())


def _list_scores(world: World):
    response = world.as_outsider("GET", "/scores")

    assert response.status_code == 200, response.text
    assert world.score_id not in [item["id"] for item in response.json()]
    assert [item for item in response.json() if item["church_id"] == world.owner_church_id] == []


def _read_score(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "GET")


def _sign_file_upload(world: World):
    _assert_indistinguishable_from_a_missing_score(
        world, "POST", "/file", json={"filename": "x.png", "content_type": "image/png"}
    )


def _open_edit(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "GET", "/edit")


def _sign_edit_upload(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "POST", "/edited-file")


def _save_edit(world: World):
    # A key the outsider is entitled to name, so the refusal is about the
    # score and not about the key.
    _assert_indistinguishable_from_a_missing_score(
        world,
        "PUT",
        "/edit",
        json={"edited_file_uri": f"scores/{world.outsider_church_id}/x.png", "edit_doc": {}},
    )


def _clear_edit(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "DELETE", "/edit")


def _update_score(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "PATCH", json={"title": "hijacked"})


def _delete_score(world: World):
    _assert_indistinguishable_from_a_missing_score(world, "DELETE")


def _list_songs(world: World):
    response = world.as_outsider("GET", "/songs")

    assert response.status_code == 200, response.text
    assert response.json() == []


def _upload_song(world: World):
    # The same title A already has: it must become B's own song, not A's.
    response = world.as_outsider(
        "POST", "/songs", json={"title": SONG_TITLE, "filename": "score.png", "content_type": "image/png"}
    )

    assert response.status_code == 201, response.text
    assert response.json()["song_id"] != world.song_id
    assert response.json()["s3_key"].startswith(f"scores/{world.outsider_church_id}/")
    listed = world.as_outsider("GET", "/songs").json()
    assert [song["song_id"] for song in listed] == [response.json()["song_id"]]


def _place_song(world: World):
    real = world.as_outsider("POST", f"/songs/{world.song_id}/usages", json={"week_of": WEEK})
    missing = world.as_outsider("POST", f"/songs/{uuid4()}/usages", json={"week_of": WEEK})

    assert real.status_code == 404, real.text
    assert (missing.status_code, missing.json()) == (real.status_code, real.json())
    # Nothing was filed under either church by the attempt.
    assert [item["id"] for item in world.client.get("/scores").json()] == [world.score_id]


def _week_pdf(world: World):
    response = world.as_outsider("GET", f"/weeks/{WEEK}/pdf")

    # The answer an empty week gives: A's song is not on B's Sunday.
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "그 주차에 등록된 곡이 없습니다."}


def _week_conti(world: World):
    response = world.as_outsider("GET", f"/weeks/{WEEK}/conti")

    assert response.status_code == 200, response.text
    assert [item for page in response.json()["pages"] for item in page] == []


def _reorder_week(world: World):
    path = f"/weeks/{WEEK}/conti/order"
    real = world.as_outsider("PATCH", path, json={"items": [{"score_id": world.score_id}]})
    missing = world.as_outsider("PATCH", path, json={"items": [{"score_id": str(uuid4())}]})

    assert real.status_code == 400, real.text
    assert (missing.status_code, missing.json()) == (real.status_code, real.json())


CASES = {
    ("GET", "/scores"): _list_scores,
    ("GET", "/scores/{score_id}"): _read_score,
    ("POST", "/scores/{score_id}/file"): _sign_file_upload,
    ("GET", "/scores/{score_id}/edit"): _open_edit,
    ("POST", "/scores/{score_id}/edited-file"): _sign_edit_upload,
    ("PUT", "/scores/{score_id}/edit"): _save_edit,
    ("DELETE", "/scores/{score_id}/edit"): _clear_edit,
    ("PATCH", "/scores/{score_id}"): _update_score,
    ("DELETE", "/scores/{score_id}"): _delete_score,
    ("GET", "/songs"): _list_songs,
    ("POST", "/songs"): _upload_song,
    ("POST", "/songs/{song_id}/usages"): _place_song,
    ("GET", "/weeks/{week_of}/pdf"): _week_pdf,
    ("GET", "/weeks/{week_of}/conti"): _week_conti,
    ("PATCH", "/weeks/{week_of}/conti/order"): _reorder_week,
}


def _served_routes() -> set[tuple[str, str]]:
    # Read off the OpenAPI document rather than app.routes: this FastAPI keeps
    # each include_router() as one opaque entry there, so walking the list one
    # level deep finds no data route at all and the check passes on nothing.
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in HTTP_METHODS
    }


def _assert_owner_data_is_untouched(world: World):
    client, owner = world.client, world.owner

    score = client.get(f"/scores/{world.score_id}", headers=owner)
    assert score.status_code == 200, score.text
    assert score.json()["title"] == SONG_TITLE
    assert score.json()["file_uri"] == world.file_uri
    assert score.json()["week_of"] == WEEK

    edit = client.get(f"/scores/{world.score_id}/edit", headers=owner)
    assert edit.json()["edited_file_uri"] is None
    assert edit.json()["edit_doc"] is None

    conti = client.get(f"/weeks/{WEEK}/conti", headers=owner)
    assert [item["score_id"] for page in conti.json()["pages"] for item in page] == [world.score_id]

    songs = client.get("/songs", headers=owner).json()
    assert [(song["song_id"], song["title"], song["use_count"]) for song in songs] == [
        (world.song_id, SONG_TITLE, 1)
    ]


def test_every_mounted_data_route_should_have_an_isolation_case():
    # Arrange
    served = _served_routes()
    accounted_for = set(CASES) | NON_DATA_ROUTES

    # Assert
    assert served == accounted_for, (
        f"routes with neither an isolation case nor an exemption: {sorted(served - accounted_for)}; "
        f"cases or exemptions for routes the app does not serve: {sorted(accounted_for - served)}"
    )


@pytest.mark.parametrize("route", sorted(CASES), ids=lambda route: f"{route[0]} {route[1]}")
def test_another_churchs_leader_should_not_reach_this_churchs_data(client, route):
    # Arrange
    world = World(client)

    # Act & Assert — each case calls its route as the outsider and judges the answer.
    CASES[route](world)

    # Assert — and whatever was answered, the owner's data is as it was.
    _assert_owner_data_is_untouched(world)
