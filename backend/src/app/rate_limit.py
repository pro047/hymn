"""Rate limiting for the auth endpoints.

Wiring /auth/check-email into the signup form turns it into an unauthenticated
oracle: anyone can walk a list of addresses and learn which ones are registered
here. A throttle does not *stop* that — 10/minute is still 14,400 probes a day
per address — but it raises the cost enough that enumerating a real mailing list
needs a proxy pool rather than a shell loop. The throttle therefore ships in the
same change as the lookup, not after it.

Why the client address comes from a header
------------------------------------------
In production the app sits behind nginx, which proxies to 127.0.0.1:8000
(`nginx/prod.nginx.conf`). The socket peer is always the proxy itself, so
slowapi's default key — the peer address — would drop every caller into a single
bucket and let one burst lock out everyone.

`X-Real-IP` is used rather than `X-Forwarded-For` because nginx sets it with
`$remote_addr`, replacing whatever the caller sent. `X-Forwarded-For` is set with
`$proxy_add_x_forwarded_for`, which *appends* to the caller's own value, so a
spoofed entry sits in front of the real one and a reader that takes the first
element hands the caller a free key of their choosing.

The header is only honoured when the socket peer is a loopback address, i.e. the
request really did arrive through the local proxy. A caller that reaches the port
directly — another process on the host, or the internet if the security group is
ever widened — is keyed on its own address and cannot pick its own bucket by
setting a header. This is defence in depth: today the EC2 security group opens
22/80/443 only (`infra/modules/ec2/main.tf`), so nothing but nginx should be able
to connect at all.

Known gap: the limits below are keyed on address alone. slowapi's key function is
synchronous and receives only the Request, so it cannot read the JSON body, which
rules out an "address + account" key. Distributed password spraying against one
account is therefore unaffected; the defence for that is a per-account failure
counter, which belongs with the service-layer work in M4.
"""

import ipaddress
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Per client address, per endpoint. Sized against what a real client produces:
# the signup form debounces and caches before it looks an address up, so a normal
# registration costs one to three CHECK_EMAIL calls; SIGNUP is a once-in-a-lifetime
# action; an access token lives an hour, so REFRESH is roughly hourly per device.
# LOGIN is the loosest of the credential paths because a church shares one public
# address behind NAT and a tight limit there would lock out everyone at once.
CHECK_EMAIL_LIMIT = "10/minute"
# CHECK_CHURCH is the same shape of unauthenticated oracle as CHECK_EMAIL — it
# answers whether a name is registered — so it gets the same budget. It reveals
# less: a church name is public where an address is not, and the answer no
# longer carries the invite code that would make knowing the name worth
# anything. ROTATE is authenticated and once-in-a-while, and is limited only so
# a stolen token cannot churn a church's code faster than its members can be told.
CHECK_CHURCH_LIMIT = "10/minute"
ROTATE_JOIN_CODE_LIMIT = "10/minute"
LOGIN_LIMIT = "10/minute"
# Authenticated and once-in-a-while, like ROTATE. It is capped anyway because a
# wrong current password is refused without touching login_guard — on purpose,
# so a stolen access token cannot lock the real owner out of /login — which
# leaves this the one credential path with no per-account counter behind it.
PASSWORD_CHANGE_LIMIT = "10/minute"
SIGNUP_LIMIT = "5/minute"
REFRESH_LIMIT = "20/minute"
LOGOUT_LIMIT = "20/minute"
ME_LIMIT = "60/minute"

RATE_LIMIT_MESSAGE = "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."

# Logged at most once per process: a proxied deployment that stops sending the
# header would otherwise collapse every visitor into one bucket in silence.
_warned_missing_real_ip = False


def _is_local_proxy(address: str) -> bool:
    """True when the socket peer is this host, i.e. our own reverse proxy."""
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    """The caller's address: from nginx when proxied, from the socket otherwise."""
    peer = get_remote_address(request) or ""

    # Reached the port directly, so there is no proxy whose header we could trust.
    # Local development and any bypass of nginx land here.
    if not _is_local_proxy(peer):
        return peer or "anonymous"

    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip

    global _warned_missing_real_ip
    if not _warned_missing_real_ip:
        _warned_missing_real_ip = True
        logger.warning(
            "Request from local proxy %s carried no X-Real-IP; rate limits are now "
            "shared by every caller. Check proxy_set_header in the nginx config.",
            peer,
        )
    return peer


# moving-window, not the "fixed-window" default: a fixed window resets whole, so a
# caller who spends the budget at 59s and again at 61s gets twice the nominal limit
# in about a second — exactly the burst these limits exist to prevent.
limiter = Limiter(key_func=client_ip, strategy="moving-window")


async def rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Answers 429 in the same shape every other error uses.

    slowapi's bundled handler returns `{"error": "5 per 1 minute"}`. The client
    reads only `detail` (see frontend/src/lib/api-error.ts), so that body would
    surface as the generic fallback sentence, in English, quoting a limit the
    user cannot act on.

    `Retry-After` carries the window length. It is an upper bound under
    moving-window — the caller may be admitted sooner — but a bound is what a
    client needs to back off instead of hammering.
    """
    return JSONResponse(
        status_code=429,
        content={"detail": RATE_LIMIT_MESSAGE},
        headers={"Retry-After": str(exc.limit.limit.get_expiry())},
    )
