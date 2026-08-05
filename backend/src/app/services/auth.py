import os
import re
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
from app.models import Church, RefreshToken, User
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
    church_code: str
    tokens: TokenBundle


def _snapshot(user: User, church: Church, tokens: TokenBundle) -> AuthResult:
    return AuthResult(
        user_id=user.id,
        church_id=user.church_id,
        email=user.email,
        name=user.name,
        role=user.role,
        church_name=church.name,
        church_code=infer_church_code(church),
        tokens=tokens,
    )


def normalize_church_code(value: str) -> str:
    code = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return code.strip("-")


def infer_church_code(church: Church) -> str:
    return normalize_church_code(church.name)


def find_church_by_code(session: Session, church_code: str) -> Church | None:
    normalized = normalize_church_code(church_code)
    churches = session.query(Church).all()
    for church in churches:
        if infer_church_code(church) == normalized:
            return church
    return None


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


def _get_or_create_church(session: Session, *, name: str, address: str) -> Church:
    church = session.query(Church).filter(Church.name == name).first()
    if church is not None:
        if not church.address:
            church.address = address
        return church
    return create_or_join_church(session, name=name, address=address)


def create_or_join_church(session: Session, *, name: str, address: str) -> Church:
    """Inserts the church, or joins the one a concurrent signup just created.

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
        return raced
    return created


def register_user(session: Session, payload: SignupRequest) -> AuthResult:
    """Creates the account and its first token pair in one transaction."""
    if session.query(User.id).filter(User.email == payload.email).first() is not None:
        raise EmailAlreadyRegisteredError

    church = _get_or_create_church(
        session, name=payload.church, address=payload.church_address
    )
    user = User(
        church_id=church.id,
        email=payload.email,
        name=payload.name,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role="member",
    )

    try:
        # The check above is a courtesy, not a guarantee: another request can
        # commit the same address in the gap. users.email is unique, so the
        # INSERT is what actually decides, and the savepoint turns losing that
        # race into a 409 instead of the 500 an unhandled IntegrityError gives.
        with session.begin_nested():
            session.add(user)
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError from exc

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
