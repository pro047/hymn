import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.fixture()
def unreachable_db(client):
    """Points the app at a database nobody is listening on.

    A real engine and a real refused connection rather than a stubbed session:
    what the probe has to survive is the driver raising, and a stub would only
    raise whatever the test guessed the driver raises.
    """
    engine = create_engine(
        "postgresql+psycopg2://nobody:nothing@127.0.0.1:1/nowhere",
        connect_args={"connect_timeout": 2},
    )

    def broken_session():
        session = Session(engine)
        try:
            yield session
        finally:
            session.close()

    # `client` has already pointed get_session at the test database; that is
    # what gets put back, so the override is never left dangling for its teardown.
    previous = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = broken_session
    yield
    app.dependency_overrides[get_session] = previous
    engine.dispose()


def test_ready_should_answer_ok_when_the_database_answers(client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_should_answer_503_when_the_database_is_unreachable(client, unreachable_db):
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_ready_should_not_leak_the_database_error_to_the_caller(client, unreachable_db):
    response = client.get("/health/ready")

    assert "127.0.0.1" not in response.text
    assert "psycopg2" not in response.text


def test_health_should_stay_ok_when_the_database_is_unreachable(client, unreachable_db):
    # The deploy script decides success on this route (deploy.yml); it must keep
    # meaning "the process is up" and nothing more.
    response = client.get("/health")

    assert response.status_code == 200
