#!/usr/bin/env python3
"""Redis-backed rate limiter and budget tracker for multi-replica llm-gateway.

The in-memory implementations in arch/rpm_budget.py work fine for a single
replica, but per-key counters reset on pod restart and aren't shared across
replicas. This module provides Redis-backed alternatives that:

- Survive pod restarts (persistent counters)
- Are shared across all replicas (consistent rate limits)
- Support TTL-based automatic window expiry

Requires a Redis instance reachable from the gateway pod.

Usage:
    from arch.redis_state import RedisRateLimiter, RedisBudgetTracker
    import redis
    r = redis.Redis(host="redis.llm.svc.cluster.local", port=6379, decode_responses=True)

    limiter = RedisRateLimiter(redis_client=r, key_alias="marketdata", rpm_limit=10)
    allowed, wait = limiter.try_consume()

    budget = RedisBudgetTracker(redis_client=r, key_alias="marketdata", max_budget_usd=20.0)
    budget.record_spend(0.05)
"""
from __future__ import annotations

import time
from typing import Optional

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover - redis is optional
    redis_lib = None


class RedisNotAvailableError(RuntimeError):
    """Raised when Redis is required but not available."""
    pass


def _ensure_redis() -> None:
    if redis_lib is None:
        raise RedisNotAvailableError(
            "redis package not installed. Add it to requirements or use in-memory "
            "implementations from arch/rpm_budget.py for single-replica deployments."
        )


# ──────────────────────────────────────────────────────────────
# Redis-backed sliding-window rate limiter
# ──────────────────────────────────────────────────────────────

class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Each request adds a timestamp to a sorted set keyed by
    `ratelimit:<key_alias>`. Old timestamps are pruned before each check.
    Window is 60 seconds.
    """

    KEY_PREFIX = "ratelimit"

    def __init__(self, redis_client, key_alias: str, rpm_limit: int,
                 window_sec: float = 60.0) -> None:
        _ensure_redis()
        if rpm_limit <= 0:
            raise ValueError("rpm_limit must be > 0")
        self.redis = redis_client
        self.key_alias = key_alias
        self.rpm_limit = rpm_limit
        self.window_sec = window_sec
        self._redis_key = f"{self.KEY_PREFIX}:{key_alias}"

    def _prune_window(self, now: float) -> None:
        cutoff = now - self.window_sec
        self.redis.zremrangebyscore(self._redis_key, 0, cutoff)

    def try_consume(self) -> tuple[bool, float]:
        """Attempt to consume one RPM token.

        Returns (allowed, wait_seconds).
        """
        now = time.time()
        self._prune_window(now)
        count = self.redis.zcard(self._redis_key)
        if count < self.rpm_limit:
            self.redis.zadd(self._redis_key, {str(now): now})
            # Set TTL on the key so it auto-expires after the window
            self.redis.expire(self._redis_key, int(self.window_sec) + 10)
            return True, 0.0
        # Get the oldest timestamp to compute wait time
        oldest = self.redis.zrange(self._redis_key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = float(oldest[0][1])
            wait = 60.0 - (now - oldest_ts)
        else:
            wait = 0.0
        return False, max(wait, 0.0)

    def reset(self) -> None:
        """Clear all rate-limit state for this key."""
        self.redis.delete(self._redis_key)

    def remaining(self) -> int:
        """Return remaining requests in current window."""
        now = time.time()
        self._prune_window(now)
        count = self.redis.zcard(self._redis_key)
        return max(0, self.rpm_limit - count)


# ──────────────────────────────────────────────────────────────
# Redis-backed per-key budget tracker
# ──────────────────────────────────────────────────────────────

class RedisBudgetTracker:
    """Per-key USD budget tracker backed by Redis.

    Stores spend as a Redis hash field and uses TTL for budget period expiry.
    """

    KEY_PREFIX = "budget"

    def __init__(self, redis_client, key_alias: str, max_budget_usd: float,
                 budget_duration: str = "30d") -> None:
        _ensure_redis()
        self.redis = redis_client
        self.key_alias = key_alias
        self.max_budget_usd = max_budget_usd
        self.budget_duration = budget_duration
        self._redis_key = f"{self.KEY_PREFIX}:{key_alias}"
        self._ttl_sec = self._parse_duration(budget_duration)

    @staticmethod
    def _parse_duration(duration: str) -> int:
        """Parse duration like '30d', '7d', '24h' into seconds."""
        duration = duration.strip().lower()
        if duration.endswith("d"):
            return int(duration[:-1]) * 86400
        if duration.endswith("h"):
            return int(duration[:-1]) * 3600
        if duration.endswith("m"):
            return int(duration[:-1]) * 60
        if duration.endswith("s"):
            return int(duration[:-1])
        # Default: 30 days
        return 30 * 86400

    @property
    def spent_usd(self) -> float:
        raw = self.redis.hget(self._redis_key, "spent_usd")
        return float(raw) if raw else 0.0

    @property
    def remaining_usd(self) -> float:
        if self.max_budget_usd <= 0:
            return float("inf")
        return max(0.0, self.max_budget_usd - self.spent_usd)

    @property
    def is_exceeded(self) -> bool:
        if self.max_budget_usd <= 0:
            return False
        return self.spent_usd > self.max_budget_usd

    def can_afford(self, estimated_cost_usd: float) -> bool:
        """Return True if the estimated cost fits within remaining budget."""
        if self.max_budget_usd <= 0:
            return True
        return (self.spent_usd + estimated_cost_usd) <= self.max_budget_usd

    def record_spend(self, amount_usd: float) -> None:
        """Add USD spend to the running total."""
        pipe = self.redis.pipeline()
        pipe.hincrbyfloat(self._redis_key, "spent_usd", amount_usd)
        pipe.expire(self._redis_key, self._ttl_sec)
        pipe.execute()

    def reset(self) -> None:
        """Reset spend counter (start of new budget period)."""
        self.redis.delete(self._redis_key)

    def stats(self) -> dict:
        return {
            "key_alias": self.key_alias,
            "max_budget_usd": self.max_budget_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "is_exceeded": self.is_exceeded,
            "ttl_sec": self._ttl_sec,
        }


# ──────────────────────────────────────────────────────────────
# Combined Redis state manager (convenience for MultiProviderRouter)
# ──────────────────────────────────────────────────────────────

class RedisStateManager:
    """Manages Redis-backed rate limiter + budget per key per provider."""

    def __init__(self, redis_client) -> None:
        _ensure_redis()
        self.redis = redis_client

    def rate_limiter(self, key_alias: str, rpm_limit: int) -> RedisRateLimiter:
        return RedisRateLimiter(
            redis_client=self.redis,
            key_alias=key_alias,
            rpm_limit=rpm_limit,
        )

    def budget_tracker(self, key_alias: str, max_budget_usd: float,
                       budget_duration: str = "30d") -> RedisBudgetTracker:
        return RedisBudgetTracker(
            redis_client=self.redis,
            key_alias=key_alias,
            max_budget_usd=max_budget_usd,
            budget_duration=budget_duration,
        )

    def health_check(self) -> bool:
        """Return True if Redis is reachable."""
        try:
            self.redis.ping()
            return True
        except Exception:
            return False


# ──────────────────────────────────────────────────────────────
# Quick CLI demo (requires redis-server)
# ──────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    if redis_lib is None:
        print("redis package not installed — cannot run demo")
        print("Install with: pip install redis")
        print("Or use in-memory implementations from arch/rpm_budget.py")
        return

    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    try:
        r = redis_lib.Redis(host=host, port=6379, decode_responses=True)
        r.ping()
    except Exception as e:
        print(f"Cannot connect to Redis at {host}:6379 — {e}")
        print("Start redis-server first, or use in-memory implementations")
        return

    limiter = RedisRateLimiter(r, key_alias="demo", rpm_limit=5)
    for i in range(7):
        allowed, wait = limiter.try_consume()
        print(f"Request {i+1}: {'allowed' if allowed else 'rate-limited'} "
              f"(wait={wait:.1f}s, remaining={limiter.remaining()})")

    budget = RedisBudgetTracker(r, key_alias="demo", max_budget_usd=1.0)
    budget.record_spend(0.30)
    print(f"\nBudget: spent=${budget.spent_usd:.2f}, remaining=${budget.remaining_usd:.2f}, "
          f"exceeded={budget.is_exceeded}")


if __name__ == "__main__":
    main()
