"""Request dependencies shared by the routers.

get_current_user used to live in routes/saved_score.py, which meant any other
router wanting it had to import from a sibling router. It is the same check for
every protected route, so it belongs beside the session dependency instead.
"""

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services.auth import decode_token, parse_bearer_token
from app.utils.s3 import get_object_bytes, object_exists

# Rendered straight to the user by the client, like the auth router's messages.
# One wording for every way a token can fail: the caller can only sign in again
# either way, and splitting them apart tells an attacker which guess got closer.
SESSION_EXPIRED_MESSAGE = "로그인이 만료되었습니다. 다시 로그인해 주세요."


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_session),
) -> User:
    """The signed-in user, or 401. Attach with Depends() to protect a route."""
    try:
        token = parse_bearer_token(authorization)
        claims = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE) from None

    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    # The token is only good for the version it was minted under. A password
    # change or a detected replay bumps user.token_version, which retires every
    # access token issued before it — the one thing that can end a stateless JWT
    # ahead of its exp. Missing tv reads as 0, so tokens predating the column
    # keep working until they expire on their own rather than all 401-ing at
    # deploy.
    if claims.get("tv", 0) != user.token_version:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)
    return user


# One wording for every leader-only route, for the same reason as above: the
# client shows it as is, and a member has the same next step whichever screen
# they were refused on.
LEADER_ONLY_MESSAGE = "인도자만 할 수 있는 작업입니다."


def require_leader(user: User = Depends(get_current_user)) -> User:
    """The signed-in user if they lead their church, or 403.

    A member account exists so that a person belongs to a church and can open
    its scores; uploading, placing, editing and arranging are the leader's.
    Checked before the route looks anything up, so a member gets the same 403
    whether or not the id in the path names something — the refusal says
    nothing about what exists.
    """
    if user.role != "leader":
        raise HTTPException(status_code=403, detail=LEADER_ONLY_MESSAGE)
    return user


def get_optional_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_session),
) -> User | None:
    """None when no Authorization header was sent; otherwise get_current_user.

    For the one route that still answers anonymous callers (GET /scores, which
    the tablets call without a login). The split is on the header's presence,
    not its validity: a header that is there but stale gets the same 401 as on
    any protected route. Falling back to anonymous instead would show a leader
    with an expired token every church's scores without a word, and the web
    client would never see the 401 that makes it refresh.
    """
    if authorization is None:
        return None
    return get_current_user(authorization=authorization, session=session)


ObjectReader = Callable[[str], bytes]


def get_object_reader() -> ObjectReader:
    """How this request reads an S3 object's bytes.

    Production resolves to app.utils.s3.get_object_bytes; a test overrides it
    with app.dependency_overrides[get_object_reader], the same seam
    get_session already uses, so no test ever opens a real S3 connection.
    """
    return get_object_bytes


ObjectProbe = Callable[[str], bool]


def get_object_probe() -> ObjectProbe:
    """How this request asks whether an S3 object exists.

    Production resolves to app.utils.s3.object_exists; tests override it the
    same way as get_object_reader.
    """
    return object_exists
