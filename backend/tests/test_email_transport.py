"""Pins which transport carries the mail, and what SES is actually asked to do.

Two switches decide whether a reset link reaches a person or a log file:
PASSWORD_RESET_ENABLED (does the route exist) and EMAIL_SENDER (what carries the
mail). Nothing in the type system makes them agree, and the one combination that
must never ship — production, feature on, console transport — writes a live
credential to the application log for every account that asks. So the agreement
between them is tested here rather than trusted.

test.md allows mocking outbound mail, which is what makes the SES request shape
assertable at all: the alternative is sending real mail from a test run.
"""

import json
import os
import subprocess
import sys

import pytest

from app.utils.email import (
    ConsoleEmailSender,
    EmailMessage,
    SesEmailSender,
    TransportMisconfigured,
    get_email_sender,
    require_deliverable_transport,
)

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

MESSAGE = EmailMessage(
    to="tester@example.com",
    subject="비밀번호 재설정 안내",
    body="아래 링크에서 새 비밀번호를 설정해 주세요.\n\nhttps://example.com?token=abc",
)


class _StubSesClient:
    """Records the call instead of making it."""

    def __init__(self):
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture(autouse=True)
def clean_transport_env(monkeypatch):
    """Every test states its own environment.

    Without this the suite would inherit whatever the developer's shell or an
    earlier test left behind, and the default-path assertions would pass or fail
    depending on the machine.
    """
    for name in ("EMAIL_SENDER", "SES_FROM_ADDRESS", "APP_ENV", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    yield


def test_the_default_transport_should_be_the_console_sender():
    """Nothing configured means nothing leaves the process."""
    assert isinstance(get_email_sender(), ConsoleEmailSender)


def test_asking_for_ses_without_a_from_address_should_refuse(monkeypatch):
    """Refused rather than defaulted.

    SES rejects an unverified sender, and deliver_password_reset swallows the
    failure — so a guessed default would fail silently, once per user, forever.
    """
    monkeypatch.setenv("EMAIL_SENDER", "ses")

    with pytest.raises(TransportMisconfigured):
        get_email_sender()


def test_ses_should_be_selected_case_insensitively_and_trimmed(monkeypatch):
    """A value pasted out of a dashboard arrives with a capital or a space.

    The console sender is the fallback for anything unrecognised, so a selector
    that read "SES " as unrecognised would quietly log credentials instead of
    sending mail — the exact failure the selector exists to prevent.
    """
    monkeypatch.setenv("EMAIL_SENDER", " SES ")
    monkeypatch.setenv("SES_FROM_ADDRESS", "no-reply@score-hymn.com")
    monkeypatch.setattr("app.utils.email._ses_client", lambda: _StubSesClient())

    assert isinstance(get_email_sender(), SesEmailSender)


def test_sending_through_ses_should_pass_utf8_on_both_the_subject_and_the_body():
    """SES defaults to 7-bit US-ASCII.

    The subject is Korean and the body always is, so an omitted charset does not
    fail — it delivers a mangled message, which is worse.
    """
    client = _StubSesClient()

    SesEmailSender(client, from_address="no-reply@score-hymn.com").send(MESSAGE)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["FromEmailAddress"] == "no-reply@score-hymn.com"
    assert call["Destination"] == {"ToAddresses": [MESSAGE.to]}
    simple = call["Content"]["Simple"]
    assert simple["Subject"] == {"Data": MESSAGE.subject, "Charset": "UTF-8"}
    assert simple["Body"]["Text"] == {"Data": MESSAGE.body, "Charset": "UTF-8"}


def test_a_failing_ses_call_should_reach_the_caller():
    """The swallow belongs to deliver_password_reset, not to the sender.

    If this class caught its own errors, that swallow could never be removed or
    narrowed — every failure would already be invisible one layer down.
    """
    class _Broken:
        def send_email(self, **kwargs):
            raise RuntimeError("SES said no")

    with pytest.raises(RuntimeError):
        SesEmailSender(_Broken(), from_address="no-reply@score-hymn.com").send(MESSAGE)


def test_the_guard_should_allow_the_console_sender_outside_production(monkeypatch):
    """The console sender *is* the dev round trip — the link in the container
    log is how the flow gets completed with no mail infrastructure."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_SENDER", "console")

    require_deliverable_transport()


def test_the_guard_should_refuse_an_absent_app_env(monkeypatch):
    """The outermost check must not be the one that fails open.

    APP_ENV is read by nothing else in the backend, so no other code path would
    notice it going missing from a deployment's env file. Defaulting it to
    "development" meant an env file that simply lacked the line skipped the
    production branch entirely — and the production branch is the one that
    stops reset links being written to the log.
    """
    monkeypatch.setenv("EMAIL_SENDER", "console")

    with pytest.raises(TransportMisconfigured) as raised:
        require_deliverable_transport()

    assert "APP_ENV" in str(raised.value)


def test_the_guard_should_refuse_an_unset_email_sender(monkeypatch):
    """Unset must not resolve to the transport that logs credentials.

    get_email_sender() still defaults to console — that is right for a
    dependency the tests override. The guard is where the choice has to be
    deliberate, because here the cost of guessing wrong is a log full of live
    reset links.
    """
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(TransportMisconfigured) as raised:
        require_deliverable_transport()

    assert "EMAIL_SENDER" in str(raised.value)


def test_the_guard_should_refuse_the_console_sender_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_SENDER", "console")

    with pytest.raises(TransportMisconfigured) as raised:
        require_deliverable_transport()

    # The message has to say what to do about it: this fires at startup, and
    # whoever reads it is looking at a container that will not boot.
    assert "EMAIL_SENDER=ses" in str(raised.value)
    assert "PASSWORD_RESET_ENABLED" in str(raised.value)


def test_the_guard_should_pass_in_production_once_ses_is_configured(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_SENDER", "ses")
    monkeypatch.setenv("SES_FROM_ADDRESS", "no-reply@score-hymn.com")
    monkeypatch.setattr(
        "app.utils.email.PASSWORD_RESET_URL_BASE", "https://www.score-hymn.com/reset-password"
    )
    monkeypatch.setattr("app.utils.email._ses_client", lambda: _StubSesClient())

    require_deliverable_transport()


def test_the_guard_should_refuse_ses_without_a_from_address_in_production(monkeypatch):
    """Checking the selector is not the same as checking what it selects.

    An earlier version tested EMAIL_SENDER alone. With SES selected and
    SES_FROM_ADDRESS missing the app booted and the route mounted, then every
    request 500'd when FastAPI resolved the dependency — the guard's whole
    premise, "do not serve this flow without a transport", quietly inverted in
    the most likely misconfiguration.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_SENDER", "ses")

    with pytest.raises(TransportMisconfigured) as raised:
        require_deliverable_transport()

    assert "SES_FROM_ADDRESS" in str(raised.value)


def test_the_guard_should_refuse_a_link_base_no_recipient_can_open(monkeypatch):
    """Real mail carrying a localhost link is worse than no mail.

    The user gets a DKIM-signed message that looks entirely legitimate, and the
    only thing in it points at their own machine. By the time that is worked
    out the token has expired and the retry is behind the 5/hour limit.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_SENDER", "ses")
    monkeypatch.setenv("SES_FROM_ADDRESS", "no-reply@score-hymn.com")
    monkeypatch.setattr("app.utils.email._ses_client", lambda: _StubSesClient())
    # The module default, i.e. nobody set the variable in the deployment.
    monkeypatch.setattr(
        "app.utils.email.PASSWORD_RESET_URL_BASE", "http://localhost:5173/reset-password"
    )

    with pytest.raises(TransportMisconfigured) as raised:
        require_deliverable_transport()

    assert "PASSWORD_RESET_URL_BASE" in str(raised.value)


def _app_paths(**env) -> subprocess.CompletedProcess:
    probe = "import json; from app.main import app; print(json.dumps(sorted(app.openapi()['paths'])))"
    return subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "PYTHONPATH": SRC_DIR, **env},
        capture_output=True,
        text=True,
    )


def test_the_app_should_refuse_to_start_with_the_flag_on_and_no_transport_in_production():
    """The guard is wired into startup, so it is tested at startup.

    A subprocess because both switches are read at import time. This is the
    whole point of the guard — the flag alone could be flipped in production
    while EMAIL_SENDER stayed at its default, and nothing else would notice.
    """
    result = _app_paths(PASSWORD_RESET_ENABLED="true", APP_ENV="production", EMAIL_SENDER="console")

    assert result.returncode != 0, result.stdout
    assert "TransportMisconfigured" in result.stderr, result.stderr


def test_the_app_should_start_in_production_when_the_flag_is_off():
    """The guard must not punish a deployment that never turned the flow on —
    which is every production deployment until SES is verified."""
    result = _app_paths(PASSWORD_RESET_ENABLED="false", APP_ENV="production", EMAIL_SENDER="console")

    assert result.returncode == 0, result.stderr
    paths = json.loads(result.stdout)
    assert not [path for path in paths if path.startswith("/auth/password-reset")]
    assert "/auth/login" in paths
