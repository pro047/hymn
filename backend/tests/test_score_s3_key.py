import re


def test_s3_key_contains_church_scope_not_placeholder(client):
    response = client.post(
        "/scores",
        json={
            "title": "Amazing Grace",
            "church_name": "Key Test Church",
            "week_of": "2026-07-19",
            "storage_type": "s3",
            "filename": "score.pdf",
            "content_type": "application/pdf",
        },
    )
    assert response.status_code == 200, response.text
    s3_key = response.json()["s3_key"]

    assert "..." not in s3_key
    assert re.fullmatch(r"scores/[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf", s3_key), s3_key
