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

The header is only honoured when the socket peer is our own infrastructure. A
caller that reaches the port directly is keyed on its own address and cannot pick
its own bucket by setting a header.

"Our own infrastructure" means loopback *or private*, and the second half is not
optional. nginx runs on the host under systemd while the app runs in a container
(`docker-compose.prod.yml`), so a request nginx proxies to 127.0.0.1:8000 reaches
the container from the docker bridge gateway — a private address, never a
loopback one. An is_loopback-only test therefore rejected the header on every
production request and dropped every visitor into one shared bucket, which turned
each per-IP limit into a global one: six signups a minute from anybody blocked
signup for everybody. It failed silently, so both warnings below matter as much
as the check itself.

Widening the trusted set is paired with narrowing what can reach the port:
`docker-compose.prod.yml` binds the backend to 127.0.0.1 rather than 0.0.0.0, so
"private address" cannot mean an unrelated host on the VPC. Today the EC2
security group also opens 22/80/443 only (`infra/modules/ec2/main.tf`).

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

# Each logged at most once per process. Both describe a deployment in which every
# visitor silently shares one bucket, which is invisible from the outside — the
# requests simply start refusing each other.
_warned_missing_real_ip = False
_warned_ignored_real_ip = False


# Spelled out rather than delegated to ipaddress.is_private, which answers "not
# globally reachable" and so includes the RFC 5737 documentation blocks —
# 203.0.113.0/24 among them, the range the tests below use to stand in for a
# public caller. Trusting those would have let this file's own tests pass while
# the predicate said yes to addresses it must refuse. A trust boundary should be
# readable in one place anyway, not inherited from a stdlib membership list that
# can grow between Python versions.
_TRUSTED_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",  # a proxy on this host
        "::1/128",
        "10.0.0.0/8",  # RFC1918: the ranges docker allocates bridge networks from
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",  # IPv6 unique-local, for a v6-enabled bridge
    )
)


def _is_trusted_proxy(address: str) -> bool:
    """True when the socket peer is our own infrastructure, not a caller.

    Private as well as loopback: see the module docstring. nginx is on the host
    and the app is in a container, so the peer is the docker bridge gateway.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _TRUSTED_PROXY_NETWORKS)


def client_ip(request: Request) -> str:
    """The caller's address: from nginx when proxied, from the socket otherwise."""
    peer = get_remote_address(request) or ""
    real_ip = (request.headers.get("x-real-ip") or "").strip()

    # Reached the port directly, so there is no proxy whose header we could trust.
    # Local development and any bypass of nginx land here.
    if not _is_trusted_proxy(peer):
        if real_ip:
            # Something is proxying us from an address we do not trust, so its
            # header is being discarded and every caller behind it shares this
            # peer's bucket. This is the exact signature of the bug that made
            # the whole fleet share one limit for months, and nothing else
            # reports it: the request still succeeds, just on the wrong key.
            global _warned_ignored_real_ip
            if not _warned_ignored_real_ip:
                _warned_ignored_real_ip = True
                logger.warning(
                    "Request from untrusted peer %s carried X-Real-IP; it is being "
                    "ignored and every caller behind that proxy now shares one rate "
                    "limit. If %s really is our proxy, add its range to "
                    "_is_trusted_proxy.",
                    peer,
                    peer,
                )
        return peer or "anonymous"

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
