"""Outbound mail, behind one seam.

Only one message is sent today — the password reset link — but the transport is
kept separate from it on purpose. The reset flow has to work in three places
that cannot share a transport: tests, where nothing may leave the process; local
development, where there is no verified SES identity; and production, where SES
is the only path out. A module-level `send_mail()` would make the first two
monkeypatch the third.

So the transport is an object with one method, resolved through
`get_email_sender` as a FastAPI dependency: production picks it from the
environment, and a test overrides it the same way it already overrides the
database session.

Two switches, and they are not the same switch. `PASSWORD_RESET_ENABLED`
(routes/auth.py) decides whether the endpoints exist at all; `EMAIL_SENDER` here
decides what carries the mail. `require_deliverable_transport` below is what
stops them from drifting into the one combination that leaks credentials —
production, feature on, console transport.
"""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

# Where the emailed link points. The token rides in the query string because the
# page has to be reachable from a mail client, which can only issue a GET — the
# page then puts it in a POST body so the *confirming* request keeps it out of
# access logs.
PASSWORD_RESET_URL_BASE = os.getenv(
    "PASSWORD_RESET_URL_BASE", "http://localhost:5173/reset-password"
)

# No product name in the subject: the site has none set anywhere (the web app's
# <title> is still "frontend"), and inventing one here would be the version
# every user sees.
PASSWORD_RESET_SUBJECT = "비밀번호 재설정 안내"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """Anything that can put a message on its way. One method, on purpose.

    Structural rather than a base class: the test double is three lines and has
    no reason to import from here, and SES needs no shared behaviour either.
    """

    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Writes the mail to the application log instead of sending it.

    This is what makes the flow testable end-to-end in dev: the reset link is in
    the log, so a developer (or a dev e2e run) can complete the round trip with
    no mail infrastructure at all. It is also why the body must contain the full
    URL rather than a bare token.
    """

    def send(self, message: EmailMessage) -> None:
        # WARNING, not INFO, and measured rather than assumed: nothing in this
        # app configures logging, so uvicorn's own config leaves the root logger
        # at WARNING and an INFO line from here never reaches the container log
        # at all — which was the first thing the dev round trip found. The level
        # also says something true: this sender means a reset link was produced
        # and nobody received it.
        logger.warning(
            "[email:console] to=%s subject=%s\n%s", message.to, message.subject, message.body
        )


class SesEmailSender:
    """Sends through Amazon SES.

    The client is injected rather than built here so a test can hand in a stub
    and assert what SES would have been asked to do. Building it inside `send`
    would leave the request shape — which is the only interesting thing in this
    class — verifiable solely against the real AWS API.
    """

    def __init__(self, client, *, from_address: str):
        self._client = client
        self._from_address = from_address

    def send(self, message: EmailMessage) -> None:
        # Charset spelled out on both parts. The subject is Korean and the body
        # always is; SES defaults to 7-bit US-ASCII and would mangle every
        # message this app sends.
        self._client.send_email(
            FromEmailAddress=self._from_address,
            Destination={"ToAddresses": [message.to]},
            Content={
                "Simple": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": message.body, "Charset": "UTF-8"}},
                }
            },
        )


class TransportMisconfigured(RuntimeError):
    """The configured transport cannot deliver mail where it is being asked to."""


def _console_in_production_message(app_env: str) -> str:
    return (
        f"PASSWORD_RESET_ENABLED is on and APP_ENV={app_env}, but EMAIL_SENDER is not 'ses'. "
        "The console sender writes the whole reset link — the credential itself — to the "
        "application log, and delivers mail to nobody. Set EMAIL_SENDER=ses with "
        "SES_FROM_ADDRESS, or turn PASSWORD_RESET_ENABLED off."
    )


# Bounded on purpose. deliver_password_reset is a sync background task, so it
# runs in anyio's threadpool — the same pool the sync route handlers use. On
# boto3's defaults (60s connect, 60s read, 5 attempts) one unreachable SES
# endpoint would hold a worker for minutes and drag down throughput on endpoints
# that have nothing to do with mail. Worst case here is ~30s.
_SES_TIMEOUTS = {"connect_timeout": 5, "read_timeout": 10, "max_attempts": 2}


@lru_cache(maxsize=1)
def _ses_client():
    """Built once. boto3 clients are thread-safe and creating one costs a
    config/credential resolution, which is not worth paying per request.

    Cached, so AWS_REGION is read once per process — it is deployment config,
    not something that changes under a running app.
    """
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sesv2",
        region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        config=Config(
            connect_timeout=_SES_TIMEOUTS["connect_timeout"],
            read_timeout=_SES_TIMEOUTS["read_timeout"],
            retries={"max_attempts": _SES_TIMEOUTS["max_attempts"], "mode": "standard"},
        ),
    )


def get_email_sender() -> EmailSender:
    """The transport for this request. A FastAPI dependency, so tests override it.

    Read from the environment on every call rather than into a module constant.
    PASSWORD_RESET_URL_BASE above is a constant because it is one value read
    once; this is a *selector*, and a constant would make every test of the
    selection need a module reload.
    """
    if os.getenv("EMAIL_SENDER", "console").strip().lower() == "ses":
        from_address = os.getenv("SES_FROM_ADDRESS", "").strip()
        if not from_address:
            # Refused rather than defaulted. SES rejects an unverified sender
            # anyway, and deliver_password_reset swallows the failure — so a
            # guessed default would fail silently, once per user, forever.
            raise TransportMisconfigured("EMAIL_SENDER=ses requires SES_FROM_ADDRESS")
        return SesEmailSender(_ses_client(), from_address=from_address)
    return ConsoleEmailSender()


def _require_usable_link_base() -> None:
    """A delivered mail with an undeliverable link is the worst of both.

    PASSWORD_RESET_URL_BASE defaults to localhost because that is what dev
    needs. Once SES is carrying real mail, an unset base means the user gets a
    genuine, DKIM-signed message whose only link points at their own machine —
    and by the time they work that out the token has expired and the retry is
    behind a 5/hour limit. Nothing else in the flow would notice.
    """
    parsed = urlparse(PASSWORD_RESET_URL_BASE.strip())
    local = {"localhost", "127.0.0.1", "::1", ""}
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "") in local:
        raise TransportMisconfigured(
            f"PASSWORD_RESET_URL_BASE is {PASSWORD_RESET_URL_BASE!r}, which no recipient "
            "can open. Set it to the public reset page, e.g. "
            "https://www.score-hymn.com/reset-password."
        )


# Both are demanded explicitly rather than defaulted, because this function is
# the one place that must not be disarmable by omission. APP_ENV in particular
# is read by nothing else in the backend — it has no other consumer that would
# notice it going missing from the deployment's env file, so an absent or
# misspelled value would silently turn the production branch below into a no-op.
_KNOWN_APP_ENVS = frozenset({"production", "development", "test"})
_KNOWN_SENDERS = frozenset({"console", "ses"})


def require_deliverable_transport() -> None:
    """Refuses to serve the reset flow unless mail can actually arrive.

    Called from main.py inside the PASSWORD_RESET_ENABLED branch, so it can only
    fire when somebody deliberately turned the feature on. Several switches
    guard this flow and nothing else made them agree: the flag could be flipped
    in production while EMAIL_SENDER stayed at its default, which is precisely
    the configuration that turns the application log into a store of live reset
    links for every account. Failing at import is loud; the alternative — a 500
    per request — is a line in a log nobody reads, next to the links.

    Every branch here fails closed, and that is the whole design. Two earlier
    versions did not:

    - one tested EMAIL_SENDER alone and let a missing SES_FROM_ADDRESS through,
      so the app booted, the route mounted, and every request 500'd when the
      dependency resolved. Checking a selector is not the same as checking that
      the thing it selects exists — hence get_email_sender() is *called*.
    - one defaulted APP_ENV to "development", so a deployment whose env file
      simply lacked APP_ENV skipped the production branch entirely. The outermost
      check was the only one that failed open, which is the worst place for it.

    Development is left alone deliberately. The console sender *is* the dev
    round trip: the link in the container log is how the flow gets completed
    with no mail infrastructure at all. It just has to be asked for by name.
    """
    app_env = os.getenv("APP_ENV", "").strip().lower()
    if app_env not in _KNOWN_APP_ENVS:
        raise TransportMisconfigured(
            f"APP_ENV is {app_env!r}; expected one of {sorted(_KNOWN_APP_ENVS)}. "
            "PASSWORD_RESET_ENABLED is on, and which transport is safe depends on "
            "this value — it is not allowed to be absent or guessed."
        )

    sender = os.getenv("EMAIL_SENDER", "").strip().lower()
    if sender not in _KNOWN_SENDERS:
        # No default. The console sender logs the reset link, so "unset" must
        # never resolve to it while the feature is on.
        raise TransportMisconfigured(
            f"EMAIL_SENDER is {sender!r}; expected one of {sorted(_KNOWN_SENDERS)}. "
            "PASSWORD_RESET_ENABLED is on, so the transport has to be chosen "
            "explicitly rather than fallen back to."
        )

    if sender == "console":
        if app_env == "production":
            raise TransportMisconfigured(_console_in_production_message(app_env))
        return

    # Raises TransportMisconfigured on its own if SES_FROM_ADDRESS is missing.
    get_email_sender()
    if app_env == "production":
        # Not in dev: pointing a real SES send at a localhost link is exactly how
        # the transport gets exercised end to end before the page exists.
        _require_usable_link_base()


def password_reset_link(token: str) -> str:
    """The URL the mail asks the user to open.

    quote() rather than raw interpolation: token_urlsafe never emits a character
    that needs escaping today, but the encoding of a secret should not depend on
    the alphabet of whatever generates it next.
    """
    return f"{PASSWORD_RESET_URL_BASE}?token={quote(token)}"


def password_reset_message(*, to: str, token: str) -> EmailMessage:
    link = password_reset_link(token)
    return EmailMessage(
        to=to,
        subject=PASSWORD_RESET_SUBJECT,
        body=(
            "비밀번호 재설정을 요청하셨습니다.\n"
            "아래 링크에서 새 비밀번호를 설정해 주세요. 링크는 30분 후 만료됩니다.\n\n"
            f"{link}\n\n"
            "본인이 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다. "
            "비밀번호는 변경되지 않습니다."
        ),
    )


def deliver_password_reset(sender: EmailSender, *, to: str, token: str) -> None:
    """Sends the reset mail, and swallows any failure to send it.

    Runs as a background task, after the 202 has already gone out, so there is
    no status left to change — and that is the point. A delivery failure that
    escaped here would be logged as a request error against an address that
    exists and never against one that does not, which is the enumeration signal
    the uniform 202 exists to remove. Starlette also propagates an exception
    raised in a background task out of the request, so an uncaught one would
    turn the 202 into a 500 for exactly those callers.
    """
    try:
        sender.send(password_reset_message(to=to, token=token))
    except Exception:
        # The message says nothing, but exc_info carries a traceback and the
        # provider's own error text — and SES puts the recipient in it, e.g.
        # "Email address is not verified. The following identities failed the
        # check in region AP-NORTHEAST-2: <address>". So this line can hold an
        # address. It never holds the token: the token is not an argument to
        # anything that raises here, and the URL is built inside the message.
        #
        # Kept as exception() rather than error() anyway. Without the traceback
        # a swallowed failure is indistinguishable from a successful send, and
        # this is the only record that a user was told 202 and got nothing.
        logger.exception("Password reset mail could not be delivered")
