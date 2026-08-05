"""Per-account login throttle.

The address limits in rate_limit.py do nothing against a spray that sends one
attempt per host from a thousand hosts: every request is the first one in its
own bucket. This counter keys on the account being attacked instead, so those
thousand attempts land in one place.

Keyed on the address the caller *typed*, not on an account that was found.
Counting only real accounts would make the lockout itself an enumeration
oracle — a lockable address would be a registered one.

Why in memory
-------------
The production image runs one uvicorn process with no --workers
(backend/Dockerfile), so a process-local counter is the whole application's
counter. Two consequences to remember: a deploy resets every counter, and
adding a worker or a second container silently splits the counter N ways. At
that point this has to move to Postgres or Redis; the interface below is
deliberately small so that swap stays a one-file change.

What this costs
---------------
Somebody who knows an address can spend MAX_FAILURES wrong passwords to lock
its owner out for the length of the window. That is a real denial of service
and it is accepted on purpose: leaving a distributed spray unbounded is worse.
It is also why the threshold is ten rather than three, and why the window is
short enough to wait out.
"""

import math
import threading
import time
from collections import OrderedDict, deque

# Ten failures inside fifteen minutes locks the address for fifteen minutes.
MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

# Bounded, because the key is attacker-controlled: spraying distinct addresses
# would otherwise grow the tally map without limit. The least recently seen
# entry is evicted, which costs that address its partial count.
MAX_TRACKED_ACCOUNTS = 10_000

ACCOUNT_LOCKED_MESSAGE = "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."

# Sync endpoints run in a threadpool, so two requests really can be in here at
# once. Each entry's read-modify-write has to be one step.
_lock = threading.Lock()

# Two maps, and the split is the point. Tallies are cheap to create — one
# failed request each — so they are attacker-controlled and get an LRU cap.
# Locks cost MAX_FAILURES failed requests each, every one of them a bcrypt
# round on this machine, and they are the only thing here with any defensive
# value. So a lock is never evicted, only expired: capping them meant a spray
# of MAX_TRACKED_ACCOUNTS junk addresses could push a locked account out of
# the map and silently unlock it, which is the attack the module exists to
# stop. Growth is bounded instead by what locks cost to create and by the
# fact that every one of them expires.
_failures: "OrderedDict[str, deque[float]]" = OrderedDict()
_locks: "OrderedDict[str, float]" = OrderedDict()


def _recent_failures(email: str, now: float) -> "deque[float] | None":
    """Failures still inside the window, or None. Caller must hold `_lock`."""
    attempts = _failures.get(email)
    if attempts is None:
        return None
    while attempts and now - attempts[0] >= WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        del _failures[email]
        return None
    return attempts


def _prune_locks(now: float) -> None:
    """Drops expired locks. Caller must hold `_lock`.

    LOCKOUT_SECONDS is a constant, so insertion order is unlock order and the
    expired ones are always at the front: this stays amortised O(1) rather
    than walking the whole map on every call.
    """
    while _locks:
        email, unlock_at = next(iter(_locks.items()))
        if unlock_at > now:
            return
        del _locks[email]


def seconds_until_unlocked(email: str, *, now: float | None = None) -> int:
    """How long the address has to wait. 0 means it is not locked."""
    now = time.monotonic() if now is None else now
    with _lock:
        _prune_locks(now)
        unlock_at = _locks.get(email)
        if unlock_at is None:
            return 0
        return max(1, math.ceil(unlock_at - now))


def record_failure(email: str, *, now: float | None = None) -> None:
    """Counts one rejected attempt, and applies the lock on the last one."""
    now = time.monotonic() if now is None else now
    with _lock:
        _prune_locks(now)
        if email in _locks:
            # Already locked; callers check first, so this only guards against
            # an attacker being able to extend their own lock indefinitely.
            return

        attempts = _recent_failures(email, now)
        if attempts is None:
            attempts = deque()
            _failures[email] = attempts
        attempts.append(now)

        if len(attempts) >= MAX_FAILURES:
            del _failures[email]
            _locks[email] = now + LOCKOUT_SECONDS
            _locks.move_to_end(email)  # keeps insertion order == unlock order
            return

        _failures.move_to_end(email)
        while len(_failures) > MAX_TRACKED_ACCOUNTS:
            _failures.popitem(last=False)


def clear(email: str) -> None:
    """Forgets an address after it signs in successfully."""
    with _lock:
        _failures.pop(email, None)
        _locks.pop(email, None)


def tracked_count() -> int:
    """How many addresses hold a partial tally. LRU-capped."""
    with _lock:
        return len(_failures)


def locked_count() -> int:
    """How many addresses are currently locked. Expiry-bounded, never evicted."""
    with _lock:
        return len(_locks)


def reset() -> None:
    """Empties every counter. For tests."""
    with _lock:
        _failures.clear()
        _locks.clear()
