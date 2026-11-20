"""Process-local TTL cache; invalidation is not shared between workers."""

from collections.abc import Callable
import math
import os
import threading
import time
from typing import Any


# Global product list, identical for all users.
PRODUCTS_LIST_KEY = "inventory:products:list"
# Bound external inventory changes to a short freshness window.
PRODUCTS_LIST_TTL = 30
# Global incident counters, without individual incident details.
INCIDENTS_SUMMARY_KEY = "incidents:summary"
# Aggregate monitoring tolerates a longer freshness window.
INCIDENTS_SUMMARY_TTL = 60
# Technical telemetry report, keyed by its resolved [start, end) window.
TELEMETRY_REPORT_TTL = 60

CACHE_ENABLED = os.getenv("TRACKFLOW_CACHE_ENABLED", "1") != "0"


class TTLCache:
    def __init__(
        self,
        default_ttl: float,
        maxsize: int = 128,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validate_ttl(default_ttl)
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        self._default_ttl = default_ttl
        self._maxsize = maxsize
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0
        self._invalidations = 0

    @staticmethod
    def _validate_ttl(ttl: float) -> None:
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("TTL must be finite and positive")

    def _remove_expired(self, now: float) -> None:
        expired = [
            key for key, (expires_at, _) in self._entries.items()
            if expires_at <= now
        ]
        for key in expired:
            del self._entries[key]

    def get(self, key: str) -> tuple[bool, Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                expires_at, value = entry
                if self._clock() < expires_at:
                    self._hits += 1
                    return True, value
                del self._entries[key]
            self._misses += 1
            return False, None

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        lifetime = self._default_ttl if ttl is None else ttl
        self._validate_ttl(lifetime)
        with self._lock:
            now = self._clock()
            expires_at = now + lifetime
            if not math.isfinite(expires_at):
                raise ValueError("Expiration must be finite")
            self._remove_expired(now)
            # Replacing a key makes it the newest insertion, not an eviction.
            self._entries.pop(key, None)
            if len(self._entries) >= self._maxsize:
                del self._entries[next(iter(self._entries))]
            self._entries[key] = (expires_at, value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                self._invalidations += 1

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [key for key in self._entries if key.startswith(prefix)]
            for key in keys:
                del self._entries[key]
            self._invalidations += len(keys)

    def clear(self) -> None:
        """Remove all entries and reset counters for an isolated measurement."""
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._invalidations = 0

    def stats(self) -> dict[str, int]:
        """Count explicit removals as invalidations, not expiration or eviction."""
        with self._lock:
            self._remove_expired(self._clock())
            return {
                "hits": self._hits,
                "misses": self._misses,
                "invalidations": self._invalidations,
                "size": len(self._entries),
            }


api_cache = TTLCache(default_ttl=INCIDENTS_SUMMARY_TTL)
# Separate store so report windows never evict the inventory or incident entries.
telemetry_report_cache = TTLCache(default_ttl=TELEMETRY_REPORT_TTL, maxsize=32)
