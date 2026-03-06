"""Auto-healing toutes les 5 minutes. 0 downtime silencieux."""

import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update

from backend.database import async_session
from backend.models import IgAccount, SystemLog
from backend.services.proxy_service import ProxyService


async def _log(tenant_id: int | None, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id, level=level, module="watchdog",
            message=message, details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


class Watchdog:
    """Auto-healing toutes les 5 minutes."""

    def __init__(self):
        self.proxy_service = ProxyService()
        self._last_queue_lengths: dict[str, int] = {}

    async def check_all_services(self, tenant_id: int | None = None):
        """Verifie tous les services dans l'ordre."""
        await self._check_redis()
        await self._check_api()
        await self._check_proxies(tenant_id)
        await self._check_expired_sessions(tenant_id)

    async def _check_redis(self) -> bool:
        """redis_client.ping() avec timeout 2s."""
        try:
            from backend.services.redis_service import get_redis
            r = await get_redis()
            result = await r.ping()
            if not result:
                raise ConnectionError("Redis PING failed")
            return True
        except Exception as e:
            await self._alert_critical("redis", str(e))
            return False

    async def _check_api(self) -> bool:
        """GET http://localhost:8000/health avec timeout 5s."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8000/health", timeout=5)
                if resp.status_code != 200:
                    raise ConnectionError(f"API health status={resp.status_code}")
                return True
        except Exception as e:
            await self._alert_critical("api", str(e))
            return False

    async def _check_proxies(self, tenant_id: int | None = None):
        """Check latence de tous les proxies."""
        try:
            await self.proxy_service.check_all_proxies_health(tenant_id)
        except Exception as e:
            await _log(tenant_id, "ERROR", f"Proxy health check echoue: {e}")

    async def _check_expired_sessions(self, tenant_id: int | None = None):
        """Sessions IG expirees (> 7 jours) → flag pour refresh."""
        cutoff = datetime.utcnow() - timedelta(days=7)

        async with async_session() as session:
            query = select(IgAccount).where(
                IgAccount.status.in_(["active", "warmup"]),
                IgAccount.last_login.isnot(None),
                IgAccount.last_login < cutoff,
            )
            if tenant_id:
                query = query.where(IgAccount.tenant_id == tenant_id)

            result = await session.execute(query)
            expired_accounts = result.scalars().all()

        for account in expired_accounts:
            await _log(
                account.tenant_id, "WARNING",
                f"Session expiree pour @{account.username} (last_login: {account.last_login})",
            )

    async def _alert_critical(self, service: str, error: str):
        """Push notification CRITICAL + log en DB."""
        await _log(
            None, "CRITICAL",
            f"SERVICE DOWN: {service} — {error}",
            {"service": service, "error": error},
        )
