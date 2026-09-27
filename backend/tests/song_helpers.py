"""Files a song on a Sunday the only way the API allows: through the library.

POST /scores used to do both in one request. Now a song is uploaded to the
library (POST /songs) and placed on a Sunday (POST /songs/{id}/usages); a
title the church already has is placed as the song it already is.
"""

from app.services.song import normalize_title


def library_song(client, headers, *, title: str, filename: str = "score.png") -> dict:
    """{"song_id", "file_uri"} of the song with this title, uploading it first
    if the church has none."""
    uploaded = client.post(
        "/songs",
        json={"title": title, "filename": filename, "content_type": "image/png"},
        headers=headers,
    )
    if uploaded.status_code == 201:
        return {"song_id": uploaded.json()["song_id"], "file_uri": uploaded.json()["s3_key"]}
    assert uploaded.status_code == 409, uploaded.text
    listed = client.get("/songs", headers=headers).json()
    return next(
        {"song_id": song["song_id"], "file_uri": song["file_uri"]}
        for song in listed
        if normalize_title(song["title"]) == normalize_title(title)
    )


def library_song_id(client, headers, *, title: str, filename: str = "score.png") -> str:
    return library_song(client, headers, title=title, filename=filename)["song_id"]


def file_usage(client, headers, *, title: str, week, filename: str = "score.png", expect: int = 200):
    """Places the song titled `title` on `week`; returns the placement response."""
    song_id = library_song_id(client, headers, title=title, filename=filename)
    response = client.post(f"/songs/{song_id}/usages", json={"week_of": str(week)}, headers=headers)
    assert response.status_code == expect, response.text
    return response
