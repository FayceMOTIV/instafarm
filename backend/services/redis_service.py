"""Queues Redis separees par niche et type d'action. Rate limiting."""

import json
import os
from datetime import datetime, timezone

import pytz
import redis.asyncio as aioredis

PARIS_TZ = pytz.timezone("Europe/Paris")

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Singleton Redis async."""
    global _redis_client
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(url, decode_responses=True)
    return _redis_client


def _queue_key(tenant_id: int, niche_id: int, action: str) -> str:
    """Cle Redis pour une queue : instafarm:{tenant_id}:{niche_id}:{action}"""
    return f"instafarm:{tenant_id}:{niche_id}:{action}"


def _rate_limit_key(account_id: int, action: str) -> str:
    """Cle rate limiting : rl:{account_id}:{action}:{date_paris}"""
    now_paris = datetime.now(PARIS_TZ)
    date_str = now_paris.strftime("%Y-%m-%d")
    return f"rl:{account_id}:{action}:{date_str}"


def _midnight_paris_epoch() -> int:
    """Timestamp epoch de minuit Paris du jour suivant (pour EXPIREAT)."""
    from datetime import timedelta
    now_paris = datetime.now(PARIS_TZ)
    tomorrow = now_paris.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow += timedelta(days=1)
    return int(tomorrow.timestamp())


def get_quota_reset_time() -> str:
    """Date de reset des quotas (minuit Paris, format YYYY-MM-DD)."""
    return datetime.now(PARIS_TZ).strftime("%Y-%m-%d")


def seconds_until_midnight_paris() -> float:
    """Nombre de secondes jusqu'au prochain minuit Paris (pour TTL Redis)."""
    now_paris = datetime.now(PARIS_TZ)
    midnight = now_paris.replace(hour=23, minute=59, second=59, microsecond=999999)
    return (midnight - now_paris).total_seconds()


class RedisService:
    """Queues Redis separees par niche et type d'action."""

    async def push_to_queue(self, tenant_id: int, niche_id: int, action: str, data: dict):
        """RPUSH instafarm:{tenant_id}:{niche_id}:{action} json(data)"""
        r = await get_redis()
        key = _queue_key(tenant_id, niche_id, action)
        await r.rpush(key, json.dumps(data, ensure_ascii=False))

    async def pop_from_queue(self, tenant_id: int, niche_id: int, action: str) -> dict | None:
        """LPOP avec deserialisation JSON."""
        r = await get_redis()
        key = _queue_key(tenant_id, niche_id, action)
        raw = await r.lpop(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def get_queue_length(self, tenant_id: int, niche_id: int, action: str) -> int:
        """LLEN pour stats PWA."""
        r = await get_redis()
        key = _queue_key(tenant_id, niche_id, action)
        return await r.llen(key)

    async def is_rate_limited(self, account_id: int, action: str, max_count: int) -> bool:
        """
        Rate limiting par compte et action.
        Si count >= max_count → return True (rate limited).
        """
        r = await get_redis()
        key = _rate_limit_key(account_id, action)
        count = await r.get(key)
        if count is None:
            return False
        return int(count) >= max_count

    async def increment_rate_limit(self, account_id: int, action: str):
        """INCR + EXPIREAT a minuit Paris."""
        r = await get_redis()
        key = _rate_limit_key(account_id, action)
        await r.incr(key)
        await r.expireat(key, _midnight_paris_epoch())

    async def reset_rate_limit(self, account_id: int, action: str):
        """Reset le rate limit pour un compte/action."""
        r = await get_redis()
        key = _rate_limit_key(account_id, action)
        await r.delete(key)

    async def get_queue_overview(self, tenant_id: int, niches: list[dict]) -> dict:
        """
        Retourne l'etat de toutes les queues pour le dashboard PWA.
        niches : list de {"id": int, "name": str}
        """
        r = await get_redis()
        result_niches = []
        total_pending = 0

        for niche_info in niches:
            niche_id = niche_info["id"]
            follows = await r.llen(_queue_key(tenant_id, niche_id, "follow"))
            dms = await r.llen(_queue_key(tenant_id, niche_id, "dm"))
            relances = await r.llen(_queue_key(tenant_id, niche_id, "relance"))
            pending = follows + dms + relances
            total_pending += pending

            result_niches.append({
                "niche_id": niche_id,
                "name": niche_info["name"],
                "follows_pending": follows,
                "dms_pending": dms,
                "relances_pending": relances,
            })

        return {"niches": result_niches, "total_pending": total_pending}

    async def ping(self) -> bool:
        """PING Redis. Retourne True si ok."""
        try:
            r = await get_redis()
            return await r.ping()
        except Exception:
            return False

    async def flush_queue(self, tenant_id: int, niche_id: int, action: str):
        """Vide une queue specifique."""
        r = await get_redis()
        key = _queue_key(tenant_id, niche_id, action)
        await r.delete(key)
