"""Reproduces the two auth races without threads.

Threads plus sleeps produce a race test that passes for timing reasons rather
than logical ones, and that goes quiet on a loaded CI runner exactly when it
would matter. Each test here arranges one precise interleaving instead:

* signup — a REPEATABLE READ snapshot, frozen before the other session commits,
  so the duplicate check still sees a free address while the unique index
  already disagrees. Unique indexes are not snapshot-based, so the INSERT is
  what discovers the conflict, which is what two simultaneous requests hit.
* refresh — the identity map. Loading the token row before the other session
  commits is the same state a concurrent request would be in when it reaches
  its DELETE, and Session.get() then serves it without another SELECT. That
  priming is the whole point: without it the loser's read simply misses and
  the test passes for the same reason the plain reuse test does.

Both tests commit for real, so they clean up after themselves rather than
riding the rollback the `db_session` fixture gives every other test.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Church, RefreshToken, User
from app.schemas.auth import SignupRequest
from app.services.auth import (
    EmailAlreadyRegisteredError,
    InvalidRefreshTokenError,
    decode_token,
    register_user,
    rotate_refresh_token,
)

CHURCH_NAME = "Concurrency Test Church"
EMAIL = "race@example.com"
SEED_EMAIL = "seed@example.com"


def _payload(**overrides) -> SignupRequest:
    return SignupRequest(
        **{
            "name": "racer",
            "email": EMAIL,
            "password": "Password1",
            "church": CHURCH_NAME,
            "church_address": "Seoul",
            "phone": "01012345678",
            "agreed_terms": True,
            **overrides,
        }
    )


@pytest.fixture()
def committed_church(engine):
    """Removes whatever the test committed, including cascaded users/tokens."""
    yield
    with Session(bind=engine) as cleanup:
        # churches.id is an ON DELETE CASCADE parent of users, which is in turn
        # one of refresh_tokens, so the one delete takes all three.
        cleanup.query(Church).filter(Church.name == CHURCH_NAME).delete()
        cleanup.commit()


def test_signup_losing_the_race_on_an_email_should_raise_rather_than_crash(
    engine, committed_church
):
    # The church has to predate the frozen snapshot. Created inside it instead,
    # the loser would collide on churches.name first and never reach the INSERT
    # this test is about.
    with Session(bind=engine) as seed:
        register_user(seed, _payload(email=SEED_EMAIL))

    frozen = engine.execution_options(isolation_level="REPEATABLE READ")
    with Session(bind=engine) as winner, Session(bind=frozen) as loser:
        # Arrange: opening a statement fixes the loser's snapshot. Anything the
        # winner commits from here on is invisible to it.
        loser.execute(text("SELECT 1"))
        register_user(winner, _payload())

        # Assert the setup itself: the loser's duplicate check still passes, so
        # the test really does reach the INSERT rather than stopping earlier.
        assert loser.query(User.id).filter(User.email == EMAIL).first() is None

        with pytest.raises(EmailAlreadyRegisteredError):
            register_user(loser, _payload())


def test_signup_losing_the_race_should_not_leave_a_half_written_account(
    engine, committed_church
):
    frozen = engine.execution_options(isolation_level="REPEATABLE READ")
    with Session(bind=engine) as winner, Session(bind=frozen) as loser:
        loser.execute(text("SELECT 1"))
        register_user(winner, _payload())
        with pytest.raises(EmailAlreadyRegisteredError):
            register_user(loser, _payload(church="Loser Church"))

    with Session(bind=engine) as check:
        assert check.query(User).filter(User.email == EMAIL).count() == 1
        # The loser had already created its church when the INSERT failed; the
        # transaction has to take that with it.
        assert check.query(Church).filter(Church.name == "Loser Church").count() == 0


def test_rotating_a_refresh_token_twice_at_once_should_revoke_rather_than_crash(
    engine, committed_church
):
    with Session(bind=engine) as setup:
        issued = register_user(setup, _payload())
    token = issued.tokens.refresh_token
    jti = decode_token(token)["jti"]

    with Session(bind=engine) as winner, Session(bind=engine) as loser:
        # Arrange: the loser holds the row before the winner spends it, which
        # is where a concurrent request would be. Read the row and delete the
        # loaded object and this is where the replay slipped through — the
        # loser's DELETE matched nothing and SQLAlchemy only warned about it,
        # so it went on to commit a second live token family.
        #
        # `primed` must stay bound. The identity map holds weak references, so
        # letting the row fall out of scope collects it, the next get() goes
        # back to the database, misses, and the test starts passing for the
        # same trivial reason the sequential reuse test does.
        primed = loser.get(RefreshToken, jti)
        assert primed is not None

        rotate_refresh_token(winner, token)

        with pytest.raises(InvalidRefreshTokenError):
            rotate_refresh_token(loser, token)

        assert primed in loser  # the reference has to survive the assertions

    with Session(bind=engine) as check:
        # Exactly one replacement token survived: the winner's.
        assert check.query(RefreshToken).count() == 1
        assert check.get(RefreshToken, jti) is None
