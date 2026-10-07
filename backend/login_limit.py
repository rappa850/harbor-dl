"""Failed sign-in throttle: too many wrong passwords for one account from one address pause further attempts."""
import time


class LoginLimit:
    def __init__(self, attempts=5, window=300, clock=time.monotonic):
        self.attempts, self.window, self.clock = attempts, window, clock
        self.failures = {}

    def _recent(self, key):
        now = self.clock()
        kept = [t for t in self.failures.get(key, []) if now - t < self.window]
        if kept:
            self.failures[key] = kept
        else:
            self.failures.pop(key, None)
        return kept

    def wait(self, address, username):
        """Seconds the caller must wait before trying again; 0 when allowed."""
        recent = self._recent((address, username.lower()))
        if len(recent) < self.attempts:
            return 0
        return max(1, int(self.window - (self.clock() - recent[0])) + 1)

    def fail(self, address, username):
        key = (address, username.lower())
        self._recent(key)
        self.failures.setdefault(key, []).append(self.clock())

    def succeed(self, address, username):
        self.failures.pop((address, username.lower()), None)
