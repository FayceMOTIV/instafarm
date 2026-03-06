"""Gestion du pool de comptes IG. Selection round-robin par anciennete."""

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from backend.bot.ig_client import QUOTAS, get_quota_tier
from backend.database import async_session
from backend.models import IgAccount, Niche


class AccountPool:
    """Gere le pool de 30 comptes IG."""

    async def get_account_for_action(
        self,
        niche_id: int,
        action: str,
        tenant_id: int,
    ) -> IgAccount | None:
        """
        Selectionne le meilleur compte disponible :
        1. Status = 'active' (warmup termine)
        2. Quotas pas atteints pour aujourd'hui
        3. Weighted round-robin par anciennete (plus vieux = prioritaire)
        4. Pas banni dans les 24 dernieres heures
        """
        async with async_session() as session:
            twenty_four_ago = datetime.utcnow() - timedelta(hours=24)

            result = await session.execute(
                select(IgAccount)
                .where(
                    IgAccount.tenant_id == tenant_id,
                    IgAccount.niche_id == niche_id,
                    IgAccount.status == "active",
                )
                .order_by(IgAccount.created_at.asc())  # Plus vieux en premier
            )
            accounts = result.scalars().all()

            for account in accounts:
                # Pas banni recemment
                if account.last_ban_at and account.last_ban_at > twenty_four_ago:
                    continue

                # Verifier quota
                tier = get_quota_tier(account)
                limits = QUOTAS[tier]

                if action == "follow" and account.follows_today >= limits["follows"]:
                    continue
                if action == "dm" and account.dms_today >= limits["dms"]:
                    continue
                if action == "like" and account.likes_today >= limits["likes"]:
                    continue

                return account

        return None

    async def reset_daily_quotas(self):
        """Remet a zero follows_today/dms_today/likes_today a minuit Paris."""
        async with async_session() as session:
            await session.execute(
                update(IgAccount)
                .values(
                    follows_today=0,
                    dms_today=0,
                    likes_today=0,
                    quota_reset_at=datetime.utcnow(),
                )
            )
            await session.commit()

    async def check_replenishment_needed(self, tenant_id: int) -> list[int]:
        """
        Verifie si des niches ont besoin de nouveaux comptes.
        Seuil : si une niche a < 2 comptes actifs → creer 1 nouveau.
        Retourne les niche_ids qui ont besoin de reconstitution.
        """
        needs_replenishment = []

        async with async_session() as session:
            # Recuperer toutes les niches du tenant
            result = await session.execute(
                select(Niche.id, Niche.name, Niche.target_account_count)
                .where(Niche.tenant_id == tenant_id, Niche.status == "active")
            )
            niches = result.all()

            for niche_id, niche_name, target_count in niches:
                # Compter les comptes actifs pour cette niche
                count_result = await session.execute(
                    select(func.count(IgAccount.id))
                    .where(
                        IgAccount.tenant_id == tenant_id,
                        IgAccount.niche_id == niche_id,
                        IgAccount.status == "active",
                    )
                )
                active_count = count_result.scalar() or 0

                if active_count < 2:
                    needs_replenishment.append(niche_id)

        return needs_replenishment

    async def get_pool_status(self, tenant_id: int) -> dict:
        """Status complet du pool de comptes."""
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount)
                .where(IgAccount.tenant_id == tenant_id)
            )
            accounts = result.scalars().all()

            total = len(accounts)
            active = sum(1 for a in accounts if a.status == "active")
            warmup = sum(1 for a in accounts if a.status == "warmup")
            banned = sum(1 for a in accounts if a.status == "banned")
            suspended = sum(1 for a in accounts if a.status == "suspended")
            paused = sum(1 for a in accounts if a.status == "paused")

            # Par niche
            niche_result = await session.execute(
                select(Niche.id, Niche.name)
                .where(Niche.tenant_id == tenant_id)
            )
            niches = niche_result.all()

            by_niche = []
            for niche_id, niche_name in niches:
                niche_accounts = [a for a in accounts if a.niche_id == niche_id]
                by_niche.append({
                    "niche_id": niche_id,
                    "niche_name": niche_name,
                    "active": sum(1 for a in niche_accounts if a.status == "active"),
                    "warmup": sum(1 for a in niche_accounts if a.status == "warmup"),
                    "banned": sum(1 for a in niche_accounts if a.status == "banned"),
                    "total": len(niche_accounts),
                })

            return {
                "total": total,
                "active": active,
                "warmup": warmup,
                "banned": banned,
                "suspended": suspended,
                "paused": paused,
                "by_niche": by_niche,
            }
