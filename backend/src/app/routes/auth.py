import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Church, RefreshToken, User
from app.schemas.auth import (
    AuthChurch,
    AuthUser,
    EmailCheckResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    SessionResponse,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from app.services.auth import (
    decode_token,
    hash_password,
    infer_church_code,
    issue_token_bundle,
    parse_bearer_token,
    verify_password_for_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])
PASSWORD_RULE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z]).{8,16}$")


@router.get("/check-email", response_model=EmailCheckResponse)
def check_email(email: str, session: Session = Depends(get_session)):
    normalized = email.strip().lower()
    exists = session.query(User.id).filter(User.email == normalized).first() is not None
    return EmailCheckResponse(available=not exists)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = (
        session.query(User)
        .filter(User.email == payload.email.strip().lower())
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password_for_user(user, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    church = session.get(Church, user.church_id)
    if church is None:
        raise HTTPException(status_code=404, detail="Church not found for user")

    tokens = issue_token_bundle(session, user=user)
    session.commit()
    return LoginResponse(
        tokens=TokenPair(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
        user=AuthUser(
            id=user.id,
            church_id=user.church_id,
            email=user.email,
            name=user.name,
            role=user.role,
        ),
        church=AuthChurch(id=church.id, name=church.name, code=infer_church_code(church)),
    )


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(payload: SignupRequest, session: Session = Depends(get_session)):
    if not payload.agreed_terms:
        raise HTTPException(status_code=400, detail="약관 동의가 필요합니다.")

    if not PASSWORD_RULE.fullmatch(payload.password):
        raise HTTPException(
            status_code=400,
            detail=(
                "비밀번호는 8~16자이며 영문 대문자와 소문자를 모두 포함해야 합니다. "
                "숫자와 특수문자는 사용할 수 있습니다."
            ),
        )

    normalized_email = payload.email.strip().lower()
    user_exists = session.query(User.id).filter(User.email == normalized_email).first()
    if user_exists:
        raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")

    church_name = payload.church.strip()
    church = session.query(Church).filter(Church.name == church_name).first()
    if church is None:
        church = Church(name=church_name, address=payload.church_address.strip())
        session.add(church)
        session.flush()
    elif not church.address:
        church.address = payload.church_address.strip()

    user = User(
        church_id=church.id,
        email=normalized_email,
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        password_hash=hash_password(payload.password),
        role="member",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.refresh(church)

    tokens = issue_token_bundle(session, user=user)
    session.commit()
    return SignupResponse(
        tokens=TokenPair(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
        user=AuthUser(
            id=user.id,
            church_id=user.church_id,
            email=user.email,
            name=user.name,
            role=user.role,
        ),
        church=AuthChurch(id=church.id, name=church.name, code=infer_church_code(church)),
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(payload: RefreshRequest, session: Session = Depends(get_session)):
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
def logout(payload: LogoutRequest, session: Session = Depends(get_session)):
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
def me(
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
