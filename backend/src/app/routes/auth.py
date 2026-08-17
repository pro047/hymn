from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_user
from app.login_guard import ACCOUNT_LOCKED_MESSAGE
from app.models import Church, User
from app.rate_limit import (
    CHECK_CHURCH_LIMIT,
    CHECK_EMAIL_LIMIT,
    LOGIN_LIMIT,
    LOGOUT_LIMIT,
    ME_LIMIT,
    PASSWORD_CHANGE_LIMIT,
    PASSWORD_RESET_CONFIRM_LIMIT,
    PASSWORD_RESET_REQUEST_LIMIT,
    REFRESH_LIMIT,
    ROTATE_JOIN_CODE_LIMIT,
    SIGNUP_LIMIT,
    limiter,
)
from app.schemas.auth import (
    AuthChurch,
    AuthUser,
    CheckChurchResponse,
    ChurchNameQuery,
    EmailCheckResponse,
    JoinCodeResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    NormalizedEmail,
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RefreshResponse,
    SessionResponse,
    SignupRequest,
    SignupResponse,
    TokenPair,
)
from app.services.auth import (
    AccountLockedError,
    AuthResult,
    ChurchMissingError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidJoinCodeError,
    InvalidPasswordResetTokenError,
    InvalidRefreshTokenError,
    NotChurchLeaderError,
    authenticate,
    begin_password_reset,
    change_password,
    decode_token,
    parse_bearer_token,
    register_user,
    reset_password,
    revoke_refresh_token,
    rotate_join_code,
    rotate_refresh_token,
    visible_join_code,
)
from app.utils.email import EmailSender, deliver_password_reset, get_email_sender

router = APIRouter(prefix="/auth", tags=["auth"])

# Every `detail` here is rendered straight to the user: api-error.ts shows the
# string as-is for a non-422 body, so an English one reaches the screen in
# English. Wording is uniform on purpose — the credentials message must not
# say which half was wrong, and the session ones must not say which check
# rejected the token.
EMAIL_TAKEN_MESSAGE = "이미 사용 중인 이메일입니다."
INVALID_CREDENTIALS_MESSAGE = "이메일 또는 비밀번호가 올바르지 않습니다."
SESSION_EXPIRED_MESSAGE = "로그인이 만료되었습니다. 다시 로그인해 주세요."
CHURCH_MISSING_MESSAGE = "계정에 연결된 교회를 찾을 수 없습니다. 관리자에게 문의해 주세요."
USER_MISSING_MESSAGE = "계정을 찾을 수 없습니다. 다시 로그인해 주세요."
# One wording for a missing code and a wrong one. Splitting them would tell a
# caller whether their guess was the right shape, and neither answer changes
# what they have to do about it.
INVALID_JOIN_CODE_MESSAGE = "초대 코드가 올바르지 않습니다. 교회 리더에게 확인해 주세요."
# Not INVALID_CREDENTIALS_MESSAGE: on this screen the caller is already signed
# in and is being asked about one field, so "이메일 또는" names something the
# form never showed them. Nothing leaks by being specific here — the account is
# already known — which is why /login cannot word itself this way.
INVALID_CURRENT_PASSWORD_MESSAGE = "현재 비밀번호가 올바르지 않습니다."
NOT_CHURCH_LEADER_MESSAGE = "교회 리더만 초대 코드를 관리할 수 있습니다."
# Expired, already used, never issued — one sentence for all three, and it names
# the only thing the caller can do about any of them.
INVALID_RESET_TOKEN_MESSAGE = "재설정 링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요."


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


@router.get("/check-church", response_model=CheckChurchResponse)
@limiter.limit(CHECK_CHURCH_LIMIT)
def check_church(request: Request, name: ChurchNameQuery, session: Session = Depends(get_session)):
    """Reports whether a church name is already registered, and nothing more.

    The signup form asks this to decide which fields to show — an invite code
    box, or a note that the caller is about to found a church. It must never
    answer with the code itself: this route is unauthenticated, and doing so
    would leave the church open to anyone who could guess its name, which is
    precisely the hole the invite code closes.
    """
    exists = session.query(Church.id).filter(Church.name == name).first() is not None
    return CheckChurchResponse(exists=exists)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: LoginRequest, session: Session = Depends(get_session)):
    try:
        result = authenticate(session, email=payload.email, password=payload.password)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=429,
            detail=ACCOUNT_LOCKED_MESSAGE,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_MESSAGE) from None
    except ChurchMissingError:
        raise HTTPException(status_code=404, detail=CHURCH_MISSING_MESSAGE) from None
    return _auth_response(LoginResponse, result)


@router.post("/signup", response_model=SignupResponse, status_code=201)
@limiter.limit(SIGNUP_LIMIT)
def signup(request: Request, payload: SignupRequest, session: Session = Depends(get_session)):
    try:
        result = register_user(session, payload)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail=EMAIL_TAKEN_MESSAGE) from None
    except InvalidJoinCodeError:
        raise HTTPException(status_code=403, detail=INVALID_JOIN_CODE_MESSAGE) from None
    return _auth_response(SignupResponse, result)


@router.post("/church/join-code", response_model=JoinCodeResponse)
@limiter.limit(ROTATE_JOIN_CODE_LIMIT)
def rotate_church_join_code(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Replaces the caller's church invite code. Leader only.

    The old code stops working the moment this returns, so the caller is told
    what the new one is — they are the only account that can read it back
    later, and losing it here would mean rotating again to find out.
    """
    try:
        code = rotate_join_code(session, user=user)
    except NotChurchLeaderError:
        raise HTTPException(status_code=403, detail=NOT_CHURCH_LEADER_MESSAGE) from None
    except ChurchMissingError:
        raise HTTPException(status_code=404, detail=CHURCH_MISSING_MESSAGE) from None
    return JoinCodeResponse(code=code)


@router.post("/password", status_code=204)
@limiter.limit(PASSWORD_CHANGE_LIMIT)
def change_own_password(
    request: Request,
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Changes the caller's password. Every session ends, this one included.

    204 with no body: the caller's own tokens were revoked on the way through
    and the client sends them to /login, so there is nothing left to say. An
    earlier version answered with a replacement token pair; once the client
    stopped keeping it, it was only a live credential in a response body.
    """
    try:
        change_password(
            session,
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError:
        # 403, not 401, and the difference is load-bearing on the client: the
        # web client reads a 401 as "this session is over" and answers it by
        # refreshing the token and retrying, then signs the user out when the
        # retry fails the same way. A typo in one field would log them out.
        # 403 is also the truer word — the caller is authenticated, and it is
        # this one request that is refused.
        raise HTTPException(status_code=403, detail=INVALID_CURRENT_PASSWORD_MESSAGE) from None


# response_class=Response so the 202 body is empty rather than the `null` that
# FastAPI would render for a route returning None. An empty body is part of the
# uniform answer: whatever is in it, both callers must get the same bytes, and
# nothing is the easiest same.
@router.post("/password-reset/request", status_code=202, response_class=Response)
@limiter.limit(PASSWORD_RESET_REQUEST_LIMIT)
def request_password_reset(
    request: Request,
    payload: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    sender: EmailSender = Depends(get_email_sender),
):
    """Mails a reset link, and says the same thing whether or not it did.

    202 with an empty body for every address, registered or not. Anything else
    — a 404, a different message, a different shape — turns this into the
    unauthenticated address oracle that /auth/check-email is rate-limited to
    make expensive, except this one would need no rate limit to be useful.

    The send is a background task for the same reason: SMTP takes hundreds of
    milliseconds and only runs for an address that exists, so sending inline
    would leave the answer in the response time. It is the same defence the
    decoy password hash provides on /login, moved to where the work is.
    """
    grant = begin_password_reset(session, email=payload.email)
    if grant is not None:
        background_tasks.add_task(
            deliver_password_reset, sender, to=grant.email, token=grant.token
        )


@router.post("/password-reset/confirm", status_code=204)
@limiter.limit(PASSWORD_RESET_CONFIRM_LIMIT)
def confirm_password_reset(
    request: Request,
    payload: PasswordResetConfirm,
    session: Session = Depends(get_session),
):
    """Sets the new password from a mailed link. Every session ends with it.

    204 and nothing back, deliberately: no token pair, not even the address the
    link belonged to. A reset is the recovery path for an account that may be in
    someone else's hands, so the caller re-authenticates with the password they
    just chose rather than being handed a live session by an unauthenticated
    request.

    401 rather than 403 for a bad link, unlike /auth/password: there is no
    session here for the web client to misread, and the caller genuinely has no
    valid credential — the link *was* the credential.
    """
    try:
        reset_password(session, token=payload.token, new_password=payload.new_password)
    except InvalidPasswordResetTokenError:
        raise HTTPException(status_code=401, detail=INVALID_RESET_TOKEN_MESSAGE) from None


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit(REFRESH_LIMIT)
def refresh(request: Request, payload: RefreshRequest, session: Session = Depends(get_session)):
    try:
        tokens = rotate_refresh_token(session, payload.refresh_token)
    except InvalidRefreshTokenError:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE) from None
    return RefreshResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=204)
@limiter.limit(LOGOUT_LIMIT)
def logout(request: Request, payload: LogoutRequest, session: Session = Depends(get_session)):
    revoke_refresh_token(session, payload.refresh_token)


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
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE) from None

    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    user_id = claims.get("sub")
    church_id = claims.get("church_id")
    if not user_id or not church_id:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=USER_MISSING_MESSAGE)

    # Same version gate as get_current_user: a token minted before the last
    # password change or replay revocation is spent, whatever its exp still says.
    if claims.get("tv", 0) != user.token_version:
        raise HTTPException(status_code=401, detail=SESSION_EXPIRED_MESSAGE)

    church = session.get(Church, church_id)
    if church is None:
        raise HTTPException(status_code=404, detail=CHURCH_MISSING_MESSAGE)

    return SessionResponse(
        user=AuthUser(
            id=user.id,
            church_id=user.church_id,
            email=user.email,
            name=user.name,
            role=user.role,
        ),
        church=AuthChurch(id=church.id, name=church.name, code=visible_join_code(user, church)),
        issued_at=datetime.fromtimestamp(int(claims.get("iat", 0)), tz=UTC),
    )
