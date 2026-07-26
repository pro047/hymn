import pytest

from app.models import User
from app.services import auth as auth_service


def _user() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000001",
        church_id="00000000-0000-0000-0000-000000000002",
        email="a@b.c",
        name="tester",
        role="member",
    )


def test_issue_token_bundle_requires_auth_secret(monkeypatch, db_session):
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth_service.issue_token_bundle(db_session, user=_user())


def test_decode_token_requires_auth_secret(monkeypatch):
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        auth_service.decode_token("some.jwt.token")
