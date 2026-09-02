"""Time-bounded cleanup of expired refresh_tokens rows.

Nothing else in this app deletes a row by age (see the design doc's grep in
.pipeline/token-sweep-b/DESIGN.md §1.1). Rows accumulate at up to one per
login/signup/refresh forever, capped only by REFRESH_TOKEN_EXPIRES_IN_SECONDS
(30 days) worth of activity. This module deletes the ones old enough that
nothing can legitimately need them any more.

Rule: delete WHERE expires_at <= now - margin. Rotated (rotated_at set) rows
are not treated differently — a rotated row's expires_at is unchanged from
when it was issued, and the margin only looks backward from now, so an active
or recently-rotated row's expires_at is never old enough to match regardless
of rotated_at. Deleting a genuinely expired rotated row costs nothing either:
its JWT already fails decode_token's exp check, so rotate_refresh_token can
never reach the code that reads rotated_at for that jti in the first place.

Why in memory
-------------
Same reasoning as login_guard: the production image runs one uvicorn process
with no --workers (backend/Dockerfile), so a process-local throttle is the
whole deployment's throttle. The throttle uses time.monotonic() (immune to
clock adjustment); the cutoff below uses naive UTC datetime (the column's own
kind), because collapsing the two onto one clock would make an NTP step wrong
one of them.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import RefreshToken

logger = logging.getLogger(__name__)

# expires_at (issue_token_bundle's `now`) and the JWT `exp` claim (_encode_token's
# separate `now`, int()-truncated) are never more than about a second apart. The
# margin absorbs that plus host clock adjustment; the cost is near zero since a
# row otherwise lives 30 days regardless.
REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS = 60 * 60
# Rows expire over 30 days, so a multi-hour delay does not affect table size.
REFRESH_SWEEP_INTERVAL_SECONDS = 60 * 60 * 6
# Bounds the lock/WAL footprint of the DELETE that runs inside a user's request.
REFRESH_SWEEP_MAX_ROWS = 1000

_lock = threading.Lock()
_last_swept_at: float | None = None


def _naive_utc_now() -> datetime:
    """UTC now, tz-naive — the shape every DateTime column in this app stores."""
    return datetime.now(UTC).replace(tzinfo=None)


def sweep_expired_refresh_tokens(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = REFRESH_SWEEP_MAX_ROWS,
) -> int:
    """Deletes up to `limit` rows with expires_at <= now - margin. Returns the count.

    Neither throttled nor guarded here — that is maybe_sweep_expired_refresh_tokens'
    job. Does not commit: the caller owns the transaction boundary, same contract
    as revoke_all_refresh_tokens. `now` is naive UTC (the column's own kind);
    None builds it internally.
    """
    now = _naive_utc_now() if now is None else now
    cutoff = now - timedelta(seconds=REFRESH_SWEEP_EXPIRY_MARGIN_SECONDS)
    candidate_ids = select(RefreshToken.id).where(RefreshToken.expires_at <= cutoff).limit(limit)
    result = session.execute(delete(RefreshToken).where(RefreshToken.id.in_(candidate_ids)))
    return result.rowcount


def maybe_sweep_expired_refresh_tokens(
    session: Session,
    *,
    now: datetime | None = None,
    clock: float | None = None,
) -> int:
    """Sweeps if the interval has elapsed; otherwise does nothing and returns 0.

    `clock` is the throttle's monotonic seconds (same contract as login_guard's
    `now: float`). `now` is naive UTC for the cutoff. Two clocks because a single
    one would make an NTP step wrong the throttle or the cutoff; see the module
    docstring.

    Runs inside a savepoint and swallows SQLAlchemyError: a cleanup failure must
    not take the caller's login/signup/refresh commit down with it. The throttle
    stamp is claimed before the sweep runs, so it advances whether or not the
    sweep succeeds — a failed sweep is retried on the next interval, not retried
    immediately, which would put every request behind it back into the same
    failure.
    """
    clock = time.monotonic() if clock is None else clock

    global _last_swept_at
    with _lock:
        if _last_swept_at is not None and clock - _last_swept_at < REFRESH_SWEEP_INTERVAL_SECONDS:
            return 0
        _last_swept_at = clock

    try:
        with session.begin_nested():
            deleted = sweep_expired_refresh_tokens(session, now=now)
    except SQLAlchemyError:
        return 0

    if deleted:
        logger.info("swept %d expired refresh tokens", deleted)
    return deleted


def reset() -> None:
    """Clears the throttle. Tests only, same spot as login_guard.reset()."""
    global _last_swept_at
    with _lock:
        _last_swept_at = None


def last_swept_at() -> float | None:
    """Monotonic time of the last sweep attempt. Tests/diagnostics only."""
    with _lock:
        return _last_swept_at
