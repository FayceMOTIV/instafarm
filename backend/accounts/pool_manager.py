"""
AccountPoolManager — Gestion du pool de comptes Instagram.

- Round-robin par niche (chaque niche a N comptes alloues)
- Health check : detecte comptes bans, resets quotas a minuit Paris
- Warmup scheduler : incremente warmup_day, change status warmup → active a J18
- Allocation proxy : max 5 comptes par proxy (REGLE ABSOLUE)
"""

import json
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from zoneinfo import ZoneInfo

from backend.database import async_session, init_db
from backend.models import IgAccount, Niche, Proxy

logger = logging.getLogger("instafarm.pool")

PARIS_TZ = ZoneInfo("Europe/Paris")

# Quotas selon l'age du compte (CLAUDE.md REGLE 4)
QUOTAS = {
    "warmup_0_7":   {"follows": 5,  "dms": 0,  "likes": 10},
    "warmup_7_14":  {"follows": 10, "dms": 3,  "likes": 20},
    "warmup_14_18": {"follows": 15, "dms": 8,  "likes": 30},
    "active_young": {"follows": 20, "dms": 12, "likes": 50},   # 18-30j
    "active_mid":   {"follows": 30, "dms": 15, "likes": 60},   # 30-90j
    "active_old":   {"follows": 40, "dms": 20, "likes": 80},   # >90j
}

# Max comptes par proxy (REGLE 3)
MAX_ACCOUNTS_PER_PROXY = 5


def get_quota_tier(warmup_day: int, status: str) -> str:
    """Determine le tier de quota selon l'age du compte."""
    if status == "warmup":
        if warmup_day < 7:
            return "warmup_0_7"
        elif warmup_day < 14:
            return "warmup_7_14"
        else:
            return "warmup_14_18"
    else:
        if warmup_day < 30:
            return "active_young"
        elif warmup_day < 90:
            return "active_mid"
        else:
            return "active_old"


def get_quotas_for_account(warmup_day: int, status: str) -> dict:
    """Retourne les quotas max pour un compte."""
    tier = get_quota_tier(warmup_day, status)
    return QUOTAS.get(tier, QUOTAS["warmup_0_7"])


class AccountPoolManager:
    """Gestionnaire du pool de comptes Instagram."""

    # ------------------------------------------------------------------
    # GET AVAILABLE ACCOUNT (round-robin par niche)
    # ------------------------------------------------------------------
    async def get_available_account(
        self,
        tenant_id: int,
        niche_id: int,
        action: str = "dm",
    ) -> IgAccount | None:
        """
        Retourne le prochain compte disponible pour une action.

        Round-robin : trie par last_action ASC (le moins utilise recemment).
        Verifie que le quota n'est pas atteint pour l'action demandee.

        Args:
            tenant_id: ID tenant
            niche_id: ID niche
            action: "dm" | "follow" | "like"

        Returns:
            IgAccount ou None si aucun disponible
        """
        async with async_session() as session:
            # Comptes actifs pour cette niche, tries par last_action ASC
            result = await session.execute(
                select(IgAccount)
                .where(
                    IgAccount.tenant_id == tenant_id,
                    IgAccount.niche_id == niche_id,
                    IgAccount.status == "active",
                )
                .order_by(IgAccount.last_action.asc().nullsfirst())
            )
            accounts = list(result.scalars().all())

            if not accounts:
                # Fallback : comptes actifs sans niche assignee
                result = await session.execute(
                    select(IgAccount)
                    .where(
                        IgAccount.tenant_id == tenant_id,
                        IgAccount.niche_id.is_(None),
                        IgAccount.status == "active",
                    )
                    .order_by(IgAccount.last_action.asc().nullsfirst())
                )
                accounts = list(result.scalars().all())

            for account in accounts:
                quotas = get_quotas_for_account(account.warmup_day, account.status)

                # Verifier quota selon l'action
                if action == "dm" and account.dms_today >= quotas["dms"]:
                    continue
                elif action == "follow" and account.follows_today >= quotas["follows"]:
                    continue
                elif action == "like" and account.likes_today >= quotas["likes"]:
                    continue

                # Verifier delai minimum entre actions (8 min)
                if account.last_action:
                    elapsed = (datetime.utcnow() - account.last_action).total_seconds()
                    if elapsed < 480:  # 8 minutes
                        continue

                logger.info(
                    f"[Pool] Compte selectionne: @{account.username} "
                    f"(dms={account.dms_today}, follows={account.follows_today})"
                )
                return account

            logger.warning(
                f"[Pool] Aucun compte disponible pour tenant={tenant_id} "
                f"niche={niche_id} action={action}"
            )
            return None

    # ------------------------------------------------------------------
    # ROTATE ACCOUNT (marquer comme utilise apres action)
    # ------------------------------------------------------------------
    async def rotate_account(
        self,
        account_id: int,
        action: str = "dm",
    ) -> None:
        """
        Met a jour le compte apres une action.
        Incremente le compteur quotidien et met a jour last_action.
        """
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount).where(IgAccount.id == account_id)
            )
            account = result.scalars().first()
            if not account:
                return

            now = datetime.utcnow()
            account.last_action = now

            if action == "dm":
                account.dms_today += 1
                account.total_dms_sent += 1
            elif action == "follow":
                account.follows_today += 1
                account.total_follows += 1
            elif action == "like":
                account.likes_today += 1

            await session.commit()
            logger.debug(f"[Pool] Rotated @{account.username} after {action}")

    # ------------------------------------------------------------------
    # HEALTH CHECK POOL
    # ------------------------------------------------------------------
    async def health_check_pool(self, tenant_id: int) -> dict:
        """
        Verifie la sante du pool de comptes.

        Returns:
            dict avec stats du pool
        """
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount).where(IgAccount.tenant_id == tenant_id)
            )
            accounts = list(result.scalars().all())

        stats = {
            "total": len(accounts),
            "active": 0,
            "warmup": 0,
            "banned": 0,
            "paused": 0,
            "suspended": 0,
            "accounts": [],
        }

        for acc in accounts:
            status = acc.status or "unknown"
            if status in stats:
                stats[status] += 1

            quotas = get_quotas_for_account(acc.warmup_day, acc.status)
            tier = get_quota_tier(acc.warmup_day, acc.status)

            stats["accounts"].append({
                "id": acc.id,
                "username": acc.username,
                "status": acc.status,
                "warmup_day": acc.warmup_day,
                "tier": tier,
                "dms_today": acc.dms_today,
                "dms_max": quotas["dms"],
                "follows_today": acc.follows_today,
                "follows_max": quotas["follows"],
                "niche_id": acc.niche_id,
                "proxy_id": acc.proxy_id,
                "last_action": acc.last_action.isoformat() if acc.last_action else None,
            })

        logger.info(
            f"[Pool] Health: {stats['total']} total, "
            f"{stats['active']} active, {stats['warmup']} warmup, "
            f"{stats['banned']} banned"
        )
        return stats

    # ------------------------------------------------------------------
    # RESET DAILY QUOTAS (minuit Paris)
    # ------------------------------------------------------------------
    async def reset_daily_quotas(self, tenant_id: int) -> int:
        """
        Reset les quotas quotidiens de tous les comptes du tenant.
        A appeler a minuit Paris.

        Returns:
            nombre de comptes resets
        """
        now = datetime.utcnow()
        async with async_session() as session:
            result = await session.execute(
                update(IgAccount)
                .where(IgAccount.tenant_id == tenant_id)
                .values(
                    follows_today=0,
                    dms_today=0,
                    likes_today=0,
                    quota_reset_at=now,
                )
                .returning(IgAccount.id)
            )
            count = len(result.all())
            await session.commit()

        logger.info(f"[Pool] Reset quotas pour {count} comptes (tenant={tenant_id})")
        return count

    # ------------------------------------------------------------------
    # WARMUP SCHEDULER
    # ------------------------------------------------------------------
    async def warmup_tick(self, tenant_id: int) -> dict:
        """
        Avance le warmup d'un jour pour tous les comptes en warmup.
        Passe en 'active' les comptes qui ont atteint J18.

        Returns:
            dict avec nb de comptes avances et actives
        """
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount).where(
                    IgAccount.tenant_id == tenant_id,
                    IgAccount.status == "warmup",
                )
            )
            warmup_accounts = list(result.scalars().all())

            advanced = 0
            activated = 0

            for acc in warmup_accounts:
                acc.warmup_day += 1
                advanced += 1

                if acc.warmup_day >= 18:
                    acc.status = "active"
                    activated += 1
                    logger.info(
                        f"[Pool] @{acc.username} passe en ACTIVE (warmup_day={acc.warmup_day})"
                    )

            await session.commit()

        logger.info(
            f"[Pool] Warmup tick: {advanced} avances, {activated} actives "
            f"(tenant={tenant_id})"
        )
        return {"advanced": advanced, "activated": activated}

    # ------------------------------------------------------------------
    # ALLOCATE PROXY
    # ------------------------------------------------------------------
    async def allocate_proxy(self, tenant_id: int) -> Proxy | None:
        """
        Trouve un proxy 4G disponible (< MAX_ACCOUNTS_PER_PROXY comptes).

        Returns:
            Proxy ou None
        """
        async with async_session() as session:
            result = await session.execute(
                select(Proxy).where(
                    Proxy.tenant_id == tenant_id,
                    Proxy.status == "active",
                    Proxy.accounts_count < MAX_ACCOUNTS_PER_PROXY,
                    Proxy.proxy_type == "4g",
                )
                .order_by(Proxy.accounts_count.asc())
            )
            proxy = result.scalars().first()

            if proxy:
                logger.info(
                    f"[Pool] Proxy alloue: {proxy.host}:{proxy.port} "
                    f"({proxy.accounts_count}/{proxy.max_accounts} comptes)"
                )
            else:
                logger.warning(
                    f"[Pool] Aucun proxy 4G disponible pour tenant={tenant_id}"
                )

            return proxy

    # ------------------------------------------------------------------
    # GET POOL STATS (resume rapide)
    # ------------------------------------------------------------------
    async def get_pool_stats(self, tenant_id: int) -> dict:
        """Stats rapides du pool sans details par compte."""
        async with async_session() as session:
            # Count par status
            result = await session.execute(
                select(
                    IgAccount.status,
                    func.count(IgAccount.id),
                )
                .where(IgAccount.tenant_id == tenant_id)
                .group_by(IgAccount.status)
            )
            rows = result.all()

        stats = {"total": 0}
        for status, count in rows:
            stats[status] = count
            stats["total"] += count

        # DMs envoyes aujourd'hui
        async with async_session() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(IgAccount.dms_today), 0))
                .where(IgAccount.tenant_id == tenant_id)
            )
            stats["dms_today_total"] = result.scalar_one()

        return stats
