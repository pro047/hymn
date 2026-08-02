from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Church, RefreshToken, User
from app.rate_limit import (
    CHECK_EMAIL_LIMIT,
    LOGIN_LIMIT,
    LOGOUT_LIMIT,
    ME_LIMIT,
    REFRESH_LIMIT,
    SIGNUP_LIMIT,
    limiter,
)
from app.schemas.auth import (
    AuthChurch,
    AuthUser,
    EmailCheckResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    NormalizedEmail,
    RefreshRequest,
    RefreshResponse,
    SessionResponse,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from app.services.auth import (
    AuthResult,
    ChurchMissingError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate,
    decode_token,
    infer_church_code,
    issue_token_bundle,
    parse_bearer_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_TAKEN_MESSAGE = "이미 사용 중인 이메일입니다."


def _auth_response(model: type[LoginResponse], result: AuthResult) -> LoginResponse:
    """Shapes the one payload /login and /signup both answer with."""
    return model(
        tokens=TokenPair(
            access_token=result.tokens.access_token,
            refresh_token=result.tokens.refresh_token,
            expires_in=result.tokens.expires_in,
        ),
        user=AuthUser(
            id=result.user_id,
            church_id=result.church_id,
            email=result.email,
            name=result.name,
            role=result.role,
        ),
        church=AuthChurch(
            id=result.church_id, name=result.church_name, code=result.church_code
        ),
    )


@router.get("/check-email", response_model=EmailCheckResponse)
@limiter.limit(CHECK_EMAIL_LIMIT)
def check_email(request: Request, email: NormalizedEmail, session: Session = Depends(get_session)):
    """Reports whether an address is free. Unauthenticated, hence the limit.

    `request` is unused by the body but required on every @limiter.limit route:
    slowapi inspects the signature while applying the decorator, so omitting it
    raises at import and the whole app — /health and the score routes included —
    fails to start.
    """
    exists = session.query(User.id).filter(User.email == email).first() is not None
    return EmailCheckResponse(available=not exists)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: LoginRequest, session: Session = Depends(get_session)):
    try:
        result = authenticate(session, email=payload.email, password=payload.password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid credentials") from None
    except ChurchMissingError:
        raise HTTPException(status_code=404, detail="Church not found for user") from None
    return _auth_response(LoginResponse, result)


@router.post("/signup", response_model=SignupResponse, status_code=201)
@limiter.limit(SIGNUP_LIMIT)
def signup(request: Request, payload: SignupRequest, session: Session = Depends(get_session)):
    try:
        result = register_user(session, payload)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN_MESSAGE) from None
    return _auth_response(SignupResponse, result)


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit(REFRESH_LIMIT)
def refresh(request: Request, payload: RefreshRequest, session: Session = Depends(get_session)):
    try:
        claims = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from None
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token type")
    user_id = claims.get("sub")
    church_id = claims.get("church_id")
    jti = claims.get("jti")
    if not user_id or not church_id or not jti:
        raise HTTPException(status_code=401, detail="Invalid refresh token claims")
    stored = session.get(RefreshToken, jti)
    if stored is None or stored.user_id != user_id:
        raise HTTPException(status_code=401, detail="Refresh token revoked")
    user = session.get(User, user_id)
    if user is None or user.church_id != church_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token subject")
    session.delete(stored)
    tokens = issue_token_bundle(session, user=user)
    session.commit()
    return RefreshResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=204)
@limiter.limit(LOGOUT_LIMIT)
def logout(request: Request, payload: LogoutRequest, session: Session = Depends(get_session)):
    if not payload.refresh_token:
        return
    try:
        claims = decode_token(payload.refresh_token)
    except JWTError:
        # Revocation is idempotent; an invalid/expired token has nothing to revoke.
        return
    jti = claims.get("jti")
    if claims.get("type") != "refresh" or not jti:
        return
    stored = session.get(RefreshToken, jti)
    if stored is not None:
        session.delete(stored)
        session.commit()
    return


@router.get("/me", response_model=SessionResponse)
@limiter.limit(ME_LIMIT)
def me(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_session),
):
    try:
        token = parse_bearer_token(authorization)
        claims = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = claims.get("sub")
    church_id = claims.get("church_id")
    if not user_id or not church_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    church = session.get(Church, church_id)
    if church is None:
        raise HTTPException(status_code=404, detail="Church not found")

    return SessionResponse(
        user=AuthUser(
            id=user.id,
            church_id=user.church_id,
            email=user.email,
            name=user.name,
            role=user.role,
        ),
        church=AuthChurch(id=church.id, name=church.name, code=infer_church_code(church)),
        issued_at=datetime.fromtimestamp(int(claims.get("iat", 0)), tz=UTC),
    )
