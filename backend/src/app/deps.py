"""Request dependencies shared by the routers.

get_current_user used to live in routes/saved_score.py, which meant any other
router wanting it had to import from a sibling router. It is the same check for
every protected route, so it belongs beside the session dependency instead.
"""

from fastapi import Depends, Header, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User
from app.services.auth import decode_token, parse_bearer_token

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
    return user
