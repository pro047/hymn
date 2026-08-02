import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


class ChurchMissingError(AuthError):
    pass


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
    user = session.query(User).filter(User.email == email).first()

    # Deliberately unconditional, and deliberately not short-circuited: both the
    # "no such account" and the "account has no password" paths must cost the
    # same bcrypt round as a genuine mismatch.
    stored_hash = user.password_hash if user is not None else None
    password_matches = pwd_context.verify(password, stored_hash or _decoy_password_hash())
    if user is None or not stored_hash or not password_matches:
        raise InvalidCredentialsError

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


def issued_at_utc() -> datetime:
    return datetime.now(UTC)


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise JWTError("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()
