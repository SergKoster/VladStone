from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

WINDOW = timedelta(minutes=10)
MAX_ATTEMPTS = 5

_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def allow_attempt(key: str, *, limit: int = MAX_ATTEMPTS, window: timedelta = WINDOW) -> bool:
    now = datetime.now(UTC)
    attempts = _attempts[key]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    return True

