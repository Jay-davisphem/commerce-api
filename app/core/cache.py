from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheService:
    """Async cache provider supporting Redis with an in-memory TTL fallback."""

    def __init__(self) -> None:
        self._memory_cache: dict[str, tuple[float, str]] = {}
        self._redis = None
        self._redis_available = False

    async def init_redis(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=1.5,
            )
            await self._redis.ping()
            self._redis_available = True
            logger.info("Connected to Redis cache backend.")
        except Exception as e:
            self._redis_available = False
            logger.info("Redis not available (%s); operating with high-speed in-memory TTL cache.", e)

    async def get(self, key: str) -> Optional[Any]:
        if self._redis_available and self._redis:
            try:
                val = await self._redis.get(key)
                return json.loads(val) if val else None
            except Exception:
                pass

        # Memory cache fallback
        record = self._memory_cache.get(key)
        if record:
            expire_at, data = record
            if time.time() < expire_at:
                return json.loads(data)
            self._memory_cache.pop(key, None)
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 120) -> None:
        serialized = json.dumps(value, default=str)
        if self._redis_available and self._redis:
            try:
                await self._redis.set(key, serialized, ex=ttl_seconds)
                return
            except Exception:
                pass

        self._memory_cache[key] = (time.time() + ttl_seconds, serialized)

    async def invalidate_prefix(self, prefix: str) -> None:
        """Evict matching cache keys on mutations."""
        if self._redis_available and self._redis:
            try:
                keys = await self._redis.keys(f"{prefix}*")
                if keys:
                    await self._redis.delete(*keys)
            except Exception:
                pass

        to_remove = [k for k in self._memory_cache if k.startswith(prefix)]
        for k in to_remove:
            self._memory_cache.pop(k, None)


cache_service = CacheService()