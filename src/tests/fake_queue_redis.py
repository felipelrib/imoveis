"""In-memory Redis double for the queue-layout tests (Story 1.18).

Implements only what the scrape single-flight and the purge script use. There
is no ``eval`` on purpose: ``BackfillLease`` then takes its token-guarded
check-then-act path, which is what these tests exercise. TTLs run on an
injectable clock so expiry is tested without sleeping.
"""

from __future__ import annotations

from typing import Callable, Optional


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeQueueRedis:
    def __init__(self, clock: Optional[Callable[[], float]] = None) -> None:
        self._clock = clock or ManualClock()
        self.kv: dict = {}
        self.expiry: dict = {}
        self.hashes: dict = {}
        self.lists: dict = {}
        self.writes: list = []  # (command, key) for "nothing was written" assertions

    # -- expiry -------------------------------------------------------------

    def _purge_expired(self, key) -> None:
        deadline = self.expiry.get(key)
        if deadline is not None and self._clock() >= deadline:
            self.kv.pop(key, None)
            self.hashes.pop(key, None)
            self.expiry.pop(key, None)

    # -- strings ------------------------------------------------------------

    def get(self, key):
        self._purge_expired(key)
        return self.kv.get(key)

    def set(self, key, value, ex=None, nx=False):
        self._purge_expired(key)
        if nx and key in self.kv:
            return None
        self.writes.append(("set", key))
        self.kv[key] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.expiry[key] = self._clock() + int(ex)
        else:
            self.expiry.pop(key, None)
        return True

    def delete(self, *keys):
        removed = 0
        for key in keys:
            self._purge_expired(key)
            self.writes.append(("delete", key))
            if key in self.kv or key in self.hashes:
                removed += 1
            self.kv.pop(key, None)
            self.hashes.pop(key, None)
            self.expiry.pop(key, None)
        return removed

    def exists(self, key):
        self._purge_expired(key)
        return int(key in self.kv or key in self.hashes)

    def expire(self, key, seconds):
        self._purge_expired(key)
        if key not in self.kv and key not in self.hashes:
            return 0
        self.writes.append(("expire", key))
        self.expiry[key] = self._clock() + int(seconds)
        return 1

    def ttl(self, key):
        self._purge_expired(key)
        if key not in self.kv and key not in self.hashes:
            return -2
        deadline = self.expiry.get(key)
        return -1 if deadline is None else int(deadline - self._clock())

    # -- hashes (lease provenance; decoration only) ---------------------------

    def hset(self, key, mapping=None, **_kwargs):
        self._purge_expired(key)
        self.writes.append(("hset", key))
        self.hashes.setdefault(key, {}).update(mapping or {})
        return len(mapping or {})

    def hgetall(self, key):
        self._purge_expired(key)
        return dict(self.hashes.get(key, {}))

    # -- keyspace -------------------------------------------------------------

    def scan_iter(self, match=None, count=None):
        import fnmatch

        for key in list(self.kv) + [k for k in self.hashes if k not in self.kv]:
            self._purge_expired(key)
            if key not in self.kv and key not in self.hashes:
                continue
            if match is None or fnmatch.fnmatchcase(str(key), match):
                yield key

    # -- lists (broker queues) ------------------------------------------------

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lrange(self, key, start, stop):
        items = self.lists.get(key, [])
        if stop == -1:
            return list(items[start:])
        return list(items[start:stop + 1])

    def lrem(self, key, count, value):
        items = self.lists.get(key, [])
        removed = 0
        while value in items and (count == 0 or removed < count):
            items.remove(value)
            removed += 1
        if removed:
            self.writes.append(("lrem", key))
        return removed
