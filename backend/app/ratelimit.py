import time
from collections import defaultdict, deque


class FailureLimiter:
    """Blocks a key after `max_failures` failures within `window` seconds. In memory: fine for the
    single app process of this deployment (restarting it forgets the counts)."""

    def __init__(self, max_failures: int = 8, window: float = 300.0):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str) -> deque[float]:
        failures = self._failures[key]
        cutoff = time.monotonic() - self.window
        while failures and failures[0] < cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return deque()
        return failures

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def retry_after(self, key: str) -> int:
        failures = self._recent(key)
        return max(1, int(self.window - (time.monotonic() - failures[0]))) if failures else 0

    def fail(self, key: str) -> None:
        self._recent(key)
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
