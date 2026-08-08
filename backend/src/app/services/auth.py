import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import PasswordValueError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import login_guard
from app.models import Church, RefreshToken, User, generate_join_code
from app.schemas.auth import SignupRequest

ACCESS_TOKEN_EXPIRES_IN_SECONDS = 60 * 60
REFRESH_TOKEN_EXPIRES_IN_SECONDS = 60 * 60 * 24 * 30
JWT_ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Base for failures the router turns into an HTTP status."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    """Too many recent failures for this address, whoever is behind them."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class ChurchMissingError(AuthError):
    pass


class InvalidJoinCodeError(AuthError):
    """No code, or the wrong one, for a church that already exists."""


class NotChurchLeaderError(AuthError):
    """A member tried to do something only the code's owner may do."""


class InvalidRefreshTokenError(AuthError):
    """One error for every way a refresh can fail.

    Undecodable, wrong type, missing claims, unknown jti, already rotated — the
    client can only do one thing about any of them, which is sign in again, so
    splitting them apart would only tell an attacker which guess got closer.
    """


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class AuthResult:
    """Everything the auth responses need, read off the ORM before the commit.

    Session.commit() expires every loaded attribute, so touching `user.email`
    afterwards issues another SELECT — and would fail outright if the session
    were closed first. Copying the values out keeps the router free of ORM
    objects and keeps the commit as the last thing that happens.
    """

    user_id: str
    church_id: str
    email: str
    name: str
    role: str
    church_name: str
    church_code: str | None
    tokens: TokenBundle


def visible_join_code(user: User, church: Church) -> str | None:
    """The church's invite code, but only to the account that may rotate it.

    Anyone holding this string can join the church and then read every score in
    it, so it goes to the leader and stops there. A member has no use for it
    that outweighs leaving a live credential in their browser storage.
    """
    return church.join_code if user.role == "leader" else None


def _snapshot(user: User, church: Church, tokens: TokenBundle) -> AuthResult:
    return AuthResult(
        user_id=user.id,
        church_id=user.church_id,
        email=user.email,
        name=user.name,
        role=user.role,
        church_name=church.name,
        church_code=visible_join_code(user, church),
        tokens=tokens,
    )


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


@lru_cache(maxsize=1)
def _decoy_password_hash() -> str:
    """A hash to check credentials against when there is no account to check.

    Skipping bcrypt for an unknown address made the miss path answer in about
    no time while a wrong password cost tens of milliseconds, so response time
    alone told a caller whether an address was registered. Verifying against
    this decoy costs the same as the real thing.

    Built lazily and cached: a module-level constant would spend a bcrypt round
    on every process start, including every test run.
    """
    return pwd_context.hash("decoy-for-timing-equalisation")


def authenticate(session: Session, *, email: str, password: str) -> AuthResult:
    """Signs a user in, or raises. `email` must already be normalized."""
    locked_for = login_guard.seconds_until_unlocked(email)
    if locked_for:
        # Checked before the password is, so a correct guess on the eleventh
        # try is refused too. A lockout that a right answer walks through is
        # not a lockout.
        raise AccountLockedError(locked_for)

    user = session.query(User).filter(User.email == email).first()

    # Deliberately unconditional, and deliberately not short-circuited: both the
    # "no such account" and the "account has no password" paths must cost the
    # same bcrypt round as a genuine mismatch.
    stored_hash = user.password_hash if user is not None else None
    try:
        password_matches = pwd_context.verify(password, stored_hash or _decoy_password_hash())
    except PasswordValueError:
        # bcrypt refuses NUL bytes and passlib raises instead of answering
        # False. hash() refuses them too, so no stored hash can ever have come
        # from such a password — it is nobody's real credential and a mismatch
        # is the honest answer. Letting it escape made /login answer 500 to any
        # unauthenticated caller and skipped the lockout tally on the way out.
        # Raised identically with and without an account, so it stays silent
        # about whether the address is registered.
        password_matches = False
    if user is None or not stored_hash or not password_matches:
        # Counted on the typed address whether or not it exists, so the
        # lockout cannot be used to tell registered addresses apart.
        login_guard.record_failure(email)
        raise InvalidCredentialsError
    login_guard.clear(email)

    church = session.get(Church, user.church_id)
    if church is None:
        raise ChurchMissingError

    tokens = issue_token_bundle(session, user=user)
    result = _snapshot(user, church, tokens)
    session.commit()
    return result


def require_join_code(church: Church, join_code: str | None) -> None:
    """Lets the signup into an existing church, or raises.

    The name on its own used to be the whole gate: knowing what a congregation
    calls itself made you a member of it, and a member passes the tenancy check
    on every score that church owns. `join_code` must already be normalized —
    SignupRequest folds case and whitespace before this sees it.

    Compared as bytes through compare_digest because the code is a shared
    secret and `==` stops at the first differing character, which is how a
    secret gets recovered one character at a time. Bytes rather than str: the
    str form of compare_digest raises TypeError on non-ASCII input, and a
    caller can put anything at all in this field.
    """
    if not join_code or not secrets.compare_digest(
        join_code.encode("utf-8"), church.join_code.encode("utf-8")
    ):
        raise InvalidJoinCodeError


def _get_or_create_church(
    session: Session, *, name: str, address: str, join_code: str | None
) -> tuple[Church, str]:
    """The church this signup joins, and the role it gets there.

    Founding a church elects you its leader: somebody has to be able to hand
    the invite code out, and the first account is the only candidate. Joining
    one costs the code and grants nothing beyond membership.
    """
    church = session.query(Church).filter(Church.name == name).first()
    if church is not None:
        # Checked before the address is filled in below: an uninvited caller
        # must not be able to edit the church they were refused.
        require_join_code(church, join_code)
        if not church.address:
            church.address = address
        return church, "member"

    created, joined_existing = create_or_join_church(session, name=name, address=address)
    if joined_existing:
        # Another signup founded this church between the read above and the
        # INSERT. The caller believed they were founding it, so they have no
        # code to offer and get the same refusal as any other uninvited join —
        # the alternative is making a stranger a member by accident of timing.
        require_join_code(created, join_code)
        return created, "member"
    return created, "leader"


def create_or_join_church(session: Session, *, name: str, address: str) -> tuple[Church, bool]:
    """Inserts the church, or returns the one a concurrent signup just created.

    The flag says which happened. The caller cannot tell from the row itself,
    and the two outcomes differ: founding elects a leader, losing the race does
    not and owes an invite code.

    Split out of _get_or_create_church so the race branch below can be reached
    on purpose. In place, it only runs when another transaction commits between
    that function's read and this INSERT, which no single-session test can
    arrange: a frozen snapshot blinds the re-read too, and READ COMMITTED makes
    the read find the row and never get here at all.
    """
    created = Church(name=name, address=address)
    try:
        # A savepoint, so losing this race costs the INSERT and nothing else.
        # Without it the failure would poison the whole transaction and take
        # the caller's signup down with it.
        with session.begin_nested():
            session.add(created)
    except IntegrityError:
        # churches.name is unique and somebody else got there first, so the
        # row the caller wanted now exists — join it rather than fail.
        # Under READ COMMITTED, which is what we run, this re-read always finds
        # it: the conflicting transaction must have committed for the INSERT to
        # have been rejected at all. The re-raise is only reachable if someone
        # raises the isolation level, and staying loud there beats returning a
        # church that is not in the caller's snapshot.
        raced = session.query(Church).filter(Church.name == name).first()
        if raced is None:
            raise
        return raced, True
    return created, False


def rotate_join_code(session: Session, *, user: User) -> str:
    """Issues a fresh invite code, retiring the one already in circulation.

    This is the whole answer to a leaked code — there is no revocation list and
    no per-invite record, so the only way to stop a string that has escaped is
    to stop honouring it.
    """
    if user.role != "leader":
        raise NotChurchLeaderError

    church = session.get(Church, user.church_id)
    if church is None:
        raise ChurchMissingError

    # Returned from the local rather than read back off the ORM: commit()
    # expires every loaded attribute, so `church.join_code` afterwards would
    # cost another SELECT — the same reason AuthResult is taken before the
    # commit rather than after it.
    code = generate_join_code()
    church.join_code = code
    session.commit()
    return code


# The two ways users.email can collide, measured against the live schema rather
# than guessed: uq_users_email is the global one an alembic migration added, and
# uq_user_church_email is the composite in models.py, which fires first when the
# duplicate lands in the same church. Anything else — a foreign key, a check —
# is not an address that is already taken and must not be reported as one.
# Renaming either constraint breaks the two signup-race tests in
# test_auth_concurrency.py, which are the only things that reach this branch.
EMAIL_UNIQUE_CONSTRAINTS = frozenset({"uq_users_email", "uq_user_church_email"})


def _violated_constraint(error: IntegrityError) -> str | None:
    """The constraint psycopg2 names in its diagnostics, if it named one."""
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def insert_new_user(session: Session, user: User) -> None:
    """Inserts the account, turning only an address clash into a 409.

    The savepoint keeps a lost race from poisoning the whole transaction, and
    the constraint check keeps 409 meaning what it says. Split out of
    register_user so both outcomes can be reached deliberately: driving a
    foreign-key failure through the full signup needs a committer to land
    between the church read and this INSERT, which a frozen snapshot cannot
    fake — it reports a serialization failure instead.
    """
    try:
        with session.begin_nested():
            session.add(user)
    except IntegrityError as exc:
        if _violated_constraint(exc) not in EMAIL_UNIQUE_CONSTRAINTS:
            # Some other constraint gave way. Answering "이미 사용 중인
            # 이메일입니다" would send the caller off to change an address that
            # was never the problem, and would bury a real fault as an expected
            # outcome. Let it surface.
            raise
        raise EmailAlreadyRegisteredError from exc


def register_user(session: Session, payload: SignupRequest) -> AuthResult:
    """Creates the account and its first token pair in one transaction."""
    # Hashed before anything is read or written. bcrypt costs ~200ms, and once
    # the church INSERT below has flushed it holds an uncommitted entry in the
    # unique index on churches.name — every other signup for that same new
    # church would then queue behind this hash, holding a pooled connection.
    password_hash = hash_password(payload.password)

    if session.query(User.id).filter(User.email == payload.email).first() is not None:
        raise EmailAlreadyRegisteredError

    church, role = _get_or_create_church(
        session,
        name=payload.church,
        address=payload.church_address,
        join_code=payload.join_code,
    )
    user = User(
        church_id=church.id,
        email=payload.email,
        name=payload.name,
        phone=payload.phone,
        password_hash=password_hash,
        role=role,
    )

    insert_new_user(session, user)

    tokens = issue_token_bundle(session, user=user)
    result = _snapshot(user, church, tokens)
    # One commit for the account, the church and the refresh token together.
    # Committing the user first and the token second could leave a registered
    # account whose signup response never arrived.
    session.commit()
    return result


def _jwt_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        raise RuntimeError("AUTH_SECRET environment variable is not set")
    return secret


def _encode_token(payload: dict, *, expires_in: int) -> str:
    now = datetime.now(UTC)
    claims = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(claims, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


def issue_token_bundle(session: Session, *, user: User) -> TokenBundle:
    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    access = _encode_token(
        {
            "sub": user.id,
            "church_id": user.church_id,
            "role": user.role,
            "type": "access",
        },
        expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
    )
    refresh = _encode_token(
        {
            "sub": user.id,
            "church_id": user.church_id,
            "type": "refresh",
            "jti": jti,
        },
        expires_in=REFRESH_TOKEN_EXPIRES_IN_SECONDS,
    )
    session.add(
        RefreshToken(
            id=jti,
            user_id=user.id,
            # DB expires_at is for cleanup only; jose enforces the exp claim.
            expires_at=(now + timedelta(seconds=REFRESH_TOKEN_EXPIRES_IN_SECONDS)).replace(tzinfo=None),
        )
    )
    return TokenBundle(
        access_token=access,
        refresh_token=refresh,
        expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
    )


def _refresh_claims(refresh_token: str) -> dict:
    try:
        claims = decode_token(refresh_token)
    except JWTError as exc:
        raise InvalidRefreshTokenError from exc
    if claims.get("type") != "refresh":
        raise InvalidRefreshTokenError
    if not (claims.get("sub") and claims.get("church_id") and claims.get("jti")):
        raise InvalidRefreshTokenError
    return claims


def _consume_refresh_token(session: Session, *, jti: str, user_id: str) -> int:
    """Deletes the stored token and reports how many rows that actually hit.

    One statement checks and spends the token, so there is no gap for a second
    request to slip into. Reading the row and then deleting the loaded object
    is what leaves that gap: both requests see the row, both issue a DELETE,
    and the loser's matches nothing. SQLAlchemy only *warns* about a DELETE
    that matched no rows (StaleDataError is for versioned UPDATEs), so the
    loser used to sail on and commit a second valid token family — the exact
    replay that rotating refresh tokens exists to catch.
    """
    return (
        session.query(RefreshToken)
        .filter(RefreshToken.id == jti, RefreshToken.user_id == user_id)
        .delete(synchronize_session=False)
    )


def rotate_refresh_token(session: Session, refresh_token: str) -> TokenBundle:
    """Spends one refresh token and issues the next pair, or raises."""
    claims = _refresh_claims(refresh_token)

    user = session.get(User, claims["sub"])
    if user is None or user.church_id != claims["church_id"]:
        raise InvalidRefreshTokenError

    if _consume_refresh_token(session, jti=claims["jti"], user_id=claims["sub"]) != 1:
        # Already spent — by a replay, or by whichever concurrent request got
        # here first. Under READ COMMITTED the loser's DELETE waits for the
        # winner to commit and then matches nothing, so exactly one of them
        # can ever pass this line.
        session.rollback()
        raise InvalidRefreshTokenError

    tokens = issue_token_bundle(session, user=user)
    session.commit()
    return tokens


def revoke_refresh_token(session: Session, refresh_token: str | None) -> None:
    """Best-effort logout. Revocation is idempotent, so nothing here raises."""
    if not refresh_token:
        return
    try:
        claims = _refresh_claims(refresh_token)
    except InvalidRefreshTokenError:
        return

    # No row count check: already revoked is the outcome logout wanted anyway.
    _consume_refresh_token(session, jti=claims["jti"], user_id=claims["sub"])
    session.commit()


def issued_at_utc() -> datetime:
    return datetime.now(UTC)


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise JWTError("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()
