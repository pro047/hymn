import hashlib
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
from app.models import Church, PasswordResetToken, RefreshToken, User, generate_join_code
from app.schemas.auth import SignupRequest

ACCESS_TOKEN_EXPIRES_IN_SECONDS = 60 * 60
REFRESH_TOKEN_EXPIRES_IN_SECONDS = 60 * 60 * 24 * 30
JWT_ALGORITHM = "HS256"
# How long after a token is rotated its re-presentation is forgiven as a race
# rather than treated as a replay. Two tabs that both read the same stored token
# and refresh at once resolve in milliseconds; a stolen token is presented
# minutes to hours after the real client last rotated it. Ten seconds sits well
# clear of the first and costs the second almost nothing — the replay is caught
# on the next presentation regardless. The stamp and the comparison both use the
# server clock, so there is no skew to widen this.
REFRESH_REUSE_GRACE_SECONDS = 10
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _naive_utc_now() -> datetime:
    """UTC now, tz-naive — the shape every DateTime column in this app stores."""
    return datetime.now(UTC).replace(tzinfo=None)


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


def _snapshot(
    user: User, church: Church, tokens: TokenBundle, *, reveal_code: bool
) -> AuthResult:
    """The payload /signup and /login share. `reveal_code` is what splits them.

    Only a founding signup has a reader for the code: it is the one unprompted
    sight of it, and the page shows it before navigating away. Login has none —
    the management page reads /auth/me instead — so sending it there put a live
    credential into every response a leader's browser, devtools panel and proxy
    log ever saw, for nobody. Keyword-only and without a default so a third
    caller has to answer the question rather than inherit an answer.
    """
    return AuthResult(
        user_id=user.id,
        church_id=user.church_id,
        email=user.email,
        name=user.name,
        role=user.role,
        church_name=church.name,
        church_code=visible_join_code(user, church) if reveal_code else None,
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
    result = _snapshot(user, church, tokens, reveal_code=False)
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
    result = _snapshot(user, church, tokens, reveal_code=True)
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
            # The version this token is valid under. A password change or a
            # replay revocation bumps user.token_version, and get_current_user
            # refuses any access token whose tv no longer matches — the only
            # thing that can retire a stateless JWT before its exp.
            "tv": user.token_version,
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


def _claim_refresh_token(session: Session, *, jti: str, user_id: str) -> int:
    """Atomically marks a live token rotated. 1 if we claimed it, 0 otherwise.

    One statement checks and spends the token, so there is no gap for a second
    request to slip into. The WHERE names rotated_at IS NULL, so under READ
    COMMITTED a concurrent loser blocks on the winner's row lock, re-reads after
    the commit, finds rotated_at now set, and matches nothing. Exactly one of
    two racers gets the 1.

    A stamp rather than a delete: the row has to survive so that presenting the
    same jti again is a replay we can see, not a missing row we would mistake
    for garbage.
    """
    return (
        session.query(RefreshToken)
        .filter(
            RefreshToken.id == jti,
            RefreshToken.user_id == user_id,
            RefreshToken.rotated_at.is_(None),
        )
        .update({RefreshToken.rotated_at: _naive_utc_now()}, synchronize_session=False)
    )


def _delete_refresh_token(session: Session, *, jti: str, user_id: str) -> int:
    """Hard-deletes one token. For logout, where there is no replay to detect."""
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

    if _claim_refresh_token(session, jti=claims["jti"], user_id=claims["sub"]) != 1:
        _reject_or_revoke_reuse(session, jti=claims["jti"], user=user)

    tokens = issue_token_bundle(session, user=user)
    session.commit()
    return tokens


def _reject_or_revoke_reuse(session: Session, *, jti: str, user: User) -> None:
    """A rotation lost the claim. Decide whether it was a race or a replay, then raise.

    The claim failed for one of three reasons: the row is gone (a logout, or a
    token that was never issued), it was rotated a moment ago (two tabs racing),
    or it was rotated long ago (a replay of a spent token). rotated_at is read
    as a column scalar, not off an ORM instance: the bulk UPDATE above leaves
    the identity map untouched, so a loaded row would answer with its stale
    pre-rotation value. The scalar always reflects the database.

    Absent or freshly rotated -> just refuse; the client recovers by adopting
    whatever token won the race. Rotated past the grace window -> the token was
    already spent, so this is a replay: end every session, access tokens
    included, and make everyone sign in again. The real client sees one 401 and
    logs back in; a thief is evicted along with it.
    """
    rotated_at = (
        session.query(RefreshToken.rotated_at)
        .filter(RefreshToken.id == jti, RefreshToken.user_id == user.id)
        .scalar()
    )
    if rotated_at is not None and (_naive_utc_now() - rotated_at).total_seconds() > REFRESH_REUSE_GRACE_SECONDS:
        revoke_all_sessions(session, user=user)
        session.commit()
    else:
        session.rollback()
    raise InvalidRefreshTokenError


def revoke_all_refresh_tokens(session: Session, *, user_id: str) -> int:
    """Signs every device out. Returns how many sessions that ended.

    Neither single-token path fits: both key on a jti, because they answer
    "this token is spent". This answers "everything issued before now is spent",
    and the caller holding one of those tokens is exactly who we are locking
    out — asking them to name it is backwards.

    Refresh tokens only. It leaves outstanding *access* tokens alive for their
    remaining hour; revoke_all_sessions is what closes that gap.
    """
    return (
        session.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id)
        .delete(synchronize_session=False)
    )


def revoke_all_sessions(session: Session, *, user: User) -> None:
    """Ends every session the user has, refresh and access alike.

    Deleting the refresh tokens stops new access tokens from being minted, but
    the ones already handed out are stateless JWTs good for up to an hour.
    Bumping token_version retires those too: each carries the version it was
    minted under, and get_current_user refuses any that no longer match. Does
    not commit — the caller owns the transaction boundary.
    """
    revoke_all_refresh_tokens(session, user_id=user.id)
    user.token_version += 1


def change_password(
    session: Session, *, user: User, current_password: str, new_password: str
) -> None:
    """Replaces the account's password and ends every session, the caller's too.

    Most password changes are prompted by somebody else knowing the old one, so
    leaving any session alive would make the change cosmetic — the other party
    keeps the access the password was protecting. Signing the caller out along
    with everyone else costs them one login and removes the question of which
    sessions were meant to survive.

    Nothing is issued in return, deliberately. An earlier version handed the
    caller a replacement pair to spare them that login; once the client decided
    to send them to /login anyway, the pair had no reader and was only a live
    credential sitting in a response body, a devtools panel and any proxy log
    along the way. Same reason the invite code came out of the login response.

    Not wired into login_guard, on purpose. Counting failures here would let an
    attacker holding a stolen access token spend ten wrong guesses and lock the
    real owner out of /login: the defence would become the attack.
    """
    stored_hash = user.password_hash
    try:
        password_matches = bool(stored_hash) and pwd_context.verify(current_password, stored_hash)
    except PasswordValueError:
        # bcrypt refuses NUL bytes and passlib raises rather than answering
        # False. current_password carries no control-character rule (a rule
        # there would lock out accounts that predate it), so this is reachable
        # from any authenticated caller — and uncaught it answers 500.
        password_matches = False
    if not password_matches:
        raise InvalidCredentialsError

    # Both bcrypt rounds are spent before the first write, so the ~200ms hash
    # is not held across an open transaction (2-D #9's rule).
    new_hash = hash_password(new_password)

    user.password_hash = new_hash
    # revoke_all_sessions, not just the refresh tokens: bumping token_version
    # here is what retires the access tokens the other party may be holding.
    # Deleting the refresh rows alone would leave a stolen access token good for
    # up to an hour after the very change meant to lock it out.
    revoke_all_sessions(session, user=user)
    # One commit for the hash, the revocations and the version bump together.
    # Committing the hash first would leave a window where the new password is
    # live and every old session still is too; committing the revocations first
    # would sign everyone out over a change that then failed to land.
    session.commit()


class InvalidPasswordResetTokenError(AuthError):
    """One error for unknown, expired and already-spent reset links alike.

    Same reasoning as InvalidRefreshTokenError: the caller's next move is to
    request a fresh link whichever it was, and telling them which would say
    whether a link they hold was ever real.
    """


# Half an hour. Long enough to walk from the request to a mail client on another
# device, short enough that a link left sitting in an inbox — the place these
# leak from — is usually already dead by the time anyone else reads it.
PASSWORD_RESET_TOKEN_TTL_SECONDS = 30 * 60
# 32 bytes from secrets, i.e. 256 bits. The token is the entire proof of email
# ownership, so it is sized like a credential rather than like a code somebody
# has to retype — nobody types this one, it arrives as a link.
PASSWORD_RESET_TOKEN_BYTES = 32


@dataclass(frozen=True)
class PasswordResetGrant:
    """A minted link, carried out to the mailer. Read before the commit, like
    AuthResult, so the caller never touches an expired ORM attribute."""

    email: str
    token: str


def _hash_reset_token(token: str) -> str:
    """What actually goes in the database.

    SHA-256 and not bcrypt: bcrypt exists to make guessing a *low-entropy*
    secret expensive, and this one is 256 random bits — there is nothing to
    guess. A slow hash here would only add ~200ms to every confirm.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def begin_password_reset(session: Session, *, email: str) -> PasswordResetGrant | None:
    """Mints a reset link for the address, or None if nobody owns it.

    None rather than an exception, because "no such account" is not an error
    here: the route answers 202 either way and simply has nothing to send. The
    address is deliberately not disclosed anywhere else in the flow.

    Any link already outstanding for the account is deleted first. Two live
    links would mean an old one — perhaps the one that was intercepted, which is
    why the user is here — keeps working after the user asked for a new one.
    """
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        return None

    session.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(token),
            expires_at=_naive_utc_now() + timedelta(seconds=PASSWORD_RESET_TOKEN_TTL_SECONDS),
        )
    )
    # Read off the local and the ORM before the commit expires them: the mailer
    # runs after this returns, and the address it needs must not cost a SELECT
    # on a session the request has already finished with.
    grant = PasswordResetGrant(email=user.email, token=token)
    session.commit()
    return grant


def _claim_password_reset_token(session: Session, *, token_hash: str) -> int:
    """Atomically spends the link. 1 if we got it, 0 if somebody else did.

    A conditional DELETE, so single-use survives two requests arriving together:
    under READ COMMITTED the loser blocks on the winner's row lock, re-reads
    after the commit, finds nothing and deletes nothing. Checking "does the row
    exist" and then deleting it would leave a gap in which both requests set a
    password — and only one of them is the person who read the mail.
    """
    return (
        session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .delete(synchronize_session=False)
    )


def reset_password(session: Session, *, token: str, new_password: str) -> None:
    """Sets a new password from a mailed link, and ends every session.

    Unlike change_password there is no current password to prove and no session
    to keep: the caller may well be someone who was locked out, and the reason
    they are here may be that somebody else has their old credentials. So every
    refresh token goes and token_version is bumped, which retires the access
    tokens already issued too, and nothing is handed back — the client sends
    them to /login with the password they just chose.
    """
    token_hash = _hash_reset_token(token)
    row = (
        session.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    if row is None or row.expires_at <= _naive_utc_now():
        raise InvalidPasswordResetTokenError

    user = session.get(User, row.user_id)
    if user is None:
        # The FK is ON DELETE CASCADE, so this is all but unreachable; it is
        # here because the alternative is an AttributeError on a live route.
        raise InvalidPasswordResetTokenError

    # Before the claim below, so the ~200ms bcrypt is not held across the row
    # lock that the DELETE takes (2-D #9's rule).
    new_hash = hash_password(new_password)

    if _claim_password_reset_token(session, token_hash=token_hash) != 1:
        # Another request spent the link between the read and here. Rolled back
        # rather than allowed through: it is one use, and the other caller has
        # already had it.
        session.rollback()
        raise InvalidPasswordResetTokenError

    user.password_hash = new_hash
    revoke_all_sessions(session, user=user)
    # One commit for the spent link, the new hash and the revocations. Splitting
    # them could leave a consumed link with the old password still live, or a
    # changed password whose link is still good for a second use.
    session.commit()


def revoke_refresh_token(session: Session, refresh_token: str | None) -> None:
    """Best-effort logout. Revocation is idempotent, so nothing here raises."""
    if not refresh_token:
        return
    try:
        claims = _refresh_claims(refresh_token)
    except InvalidRefreshTokenError:
        return

    # Hard delete, and no row-count check: already gone is the outcome logout
    # wanted. Rotation stamps rather than deletes so a replay stays visible, but
    # a deliberate logout has no replay to catch — the row can just go.
    _delete_refresh_token(session, jti=claims["jti"], user_id=claims["sub"])
    session.commit()


def issued_at_utc() -> datetime:
    return datetime.now(UTC)


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise JWTError("Missing bearer token")
    return authorization.split(" ", 1)[1].strip()
