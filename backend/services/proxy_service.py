"""Gestion des proxies 4G."""

import time
from datetime import datetime

import httpx
from sqlalchemy import select, update

from backend.database import async_session
from backend.models import Proxy


class ProxyService:
    """Gestion des proxies 4G."""

    async def get_best_proxy(self, tenant_id: int) -> Proxy | None:
        """Proxy avec accounts_count < max_accounts et latency_ms la plus basse."""
        async with async_session() as session:
            result = await session.execute(
                select(Proxy)
                .where(
                    Proxy.tenant_id == tenant_id,
                    Proxy.status == "active",
                    Proxy.accounts_count < Proxy.max_accounts,
                )
                .order_by(Proxy.latency_ms.asc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def check_all_proxies_health(self, tenant_id: int | None = None):
        """Ping tous les proxies, met a jour latency_ms et status."""
        async with async_session() as session:
            query = select(Proxy)
            if tenant_id is not None:
                query = query.where(Proxy.tenant_id == tenant_id)

            result = await session.execute(query)
            proxies = result.scalars().all()

        for proxy in proxies:
            latency, is_alive = await self._ping_proxy(proxy)
            async with async_session() as session:
                new_status = "active" if is_alive else "dead"
                if is_alive and latency > 5000:
                    new_status = "slow"

                await session.execute(
                    update(Proxy)
                    .where(Proxy.id == proxy.id)
                    .values(
                        latency_ms=latency,
                        status=new_status,
                        last_check=datetime.utcnow(),
                    )
                )
                await session.commit()

    async def _ping_proxy(self, proxy: Proxy) -> tuple[int, bool]:
        """Ping un proxy et retourne (latency_ms, is_alive)."""
        proxy_url = self.format_proxy_for_instagrapi(proxy)
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(
                proxies={"https://": proxy_url, "http://": proxy_url},
                timeout=10,
            ) as client:
                resp = await client.get("https://httpbin.org/ip")
                elapsed_ms = int((time.monotonic() - start) * 1000)
                return elapsed_ms, resp.status_code == 200
        except Exception:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return elapsed_ms, False

    def format_proxy_for_playwright(self, proxy: Proxy) -> dict:
        """Format pour Playwright."""
        result = {"server": f"http://{proxy.host}:{proxy.port}"}
        if proxy.username and proxy.password:
            result["username"] = proxy.username
            result["password"] = proxy.password
        return result

    def format_proxy_for_instagrapi(self, proxy: Proxy) -> str:
        """Format pour instagrapi : http://user:pass@host:port"""
        if proxy.username and proxy.password:
            return f"http://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}"
        return f"http://{proxy.host}:{proxy.port}"
