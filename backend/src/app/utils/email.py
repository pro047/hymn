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
database session. The SES implementation lands in the next commit; until then
the console sender is what both dev and production get, which is safe to deploy
because a link printed to the log is a link nobody receives — the flow is not
reachable from the UI yet either.
"""

import logging
import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

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


def get_email_sender() -> EmailSender:
    """The transport for this request. A FastAPI dependency, so tests override it."""
    return ConsoleEmailSender()


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
        # No address, no token: this line reaches the same log a support ticket
        # would quote. That the send failed is all it may say.
        logger.exception("Password reset mail could not be delivered")
