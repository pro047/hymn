import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models import Church, User


ACCESS_TOKEN_EXPIRES_IN_SECONDS = 60 * 60
REFRESH_TOKEN_EXPIRES_IN_SECONDS = 60 * 60 * 24 * 30
JWT_ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_in: int


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


def verify_password_for_user(user: User, password: str) -> bool:
    if not user.password_hash:
        return False
    return pwd_context.verify(password, user.password_hash)


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def _jwt_secret() -> str:
    return os.getenv("AUTH_SECRET", "dev-insecure-auth-secret")


def _encode_token(payload: dict, *, expires_in: int) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jwt.encode(claims, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


def issue_token_bundle(*, user: User) -> TokenBundle:
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
        },
        expires_in=REFRESH_TOKEN_EXPIRES_IN_SECONDS,
    )
    return TokenBundle(
        access_token=access,
        refresh_token=refresh,
        expires_in=ACCESS_TOKEN_EXPIRES_IN_SECONDS,
    )


def issued_at_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise JWTError("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()
