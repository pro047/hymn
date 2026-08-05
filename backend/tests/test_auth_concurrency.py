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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Church, RefreshToken, User
from app.schemas.auth import SignupRequest
from app.services.auth import (
    EmailAlreadyRegisteredError,
    InvalidRefreshTokenError,
    create_or_join_church,
    decode_token,
    insert_new_user,
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


def test_inserting_a_user_whose_address_is_taken_should_raise_the_duplicate_error(
    engine, committed_church
):
    """Also pins the constraint names against the live schema.

    insert_new_user answers 409 only for the constraints it lists, and those
    names are strings the code cannot derive — uq_users_email comes from an
    alembic migration rather than models.py. Rename one and this fails here,
    instead of turning every raced signup into a 500 in production.
    """
    with Session(bind=engine) as setup:
        register_user(setup, _payload())

    with Session(bind=engine) as session:
        church_id = session.query(Church.id).filter(Church.name == CHURCH_NAME).scalar()

        with pytest.raises(EmailAlreadyRegisteredError):
            insert_new_user(
                session,
                User(church_id=church_id, email=EMAIL, name="dup", password_hash="x", role="member"),
            )


def test_inserting_a_user_that_breaks_another_constraint_should_not_claim_the_address(
    engine, committed_church
):
    """409 means "that address is taken", and nothing else may borrow it.

    Mapping every IntegrityError to it sent the caller off to change an address
    that was never the problem — they would change it, retry, and get the same
    409 forever — while a genuine fault was logged as an expected outcome.
    """
    with Session(bind=engine) as session:
        session.add(Church(name=CHURCH_NAME, address="Seoul"))
        session.commit()

        # A church id that does not exist, so the foreign key gives way rather
        # than the unique index on the address.
        orphan = User(
            church_id="00000000-0000-0000-0000-000000000000",
            email="fk@example.com",
            name="fk",
            password_hash="x",
            role="member",
        )

        with pytest.raises(IntegrityError):
            insert_new_user(session, orphan)


def test_creating_a_church_that_already_exists_should_join_it_instead_of_failing(
    engine, committed_church
):
    """The other side of the signup race: two people register the first accounts
    of one new church at the same moment. The loser's INSERT hits churches.name,
    and it has to join the winner's row rather than surface a 500.

    Called directly rather than through register_user, because reaching this
    branch from there needs a committer to land between the read and the INSERT
    — see the function's own docstring.
    """
    with Session(bind=engine) as winner:
        winner.add(Church(name=CHURCH_NAME, address="Seoul"))
        winner.commit()
        winner_id = winner.query(Church.id).filter(Church.name == CHURCH_NAME).scalar()

    with Session(bind=engine) as loser:
        joined = create_or_join_church(loser, name=CHURCH_NAME, address="Busan")

        assert joined.id == winner_id
        # The loser's address must not overwrite the winner's; it lost.
        assert joined.address == "Seoul"

    with Session(bind=engine) as check:
        assert check.query(Church).filter(Church.name == CHURCH_NAME).count() == 1


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
