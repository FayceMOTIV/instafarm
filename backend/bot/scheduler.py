"""Orchestrateur principal InstaFarm. asyncio.gather pour vrai parallelisme."""

import asyncio
import json
import logging
from datetime import datetime

import pytz
from sqlalchemy import func, select

from backend.bot.anti_ban import AntiBanEngine
from backend.bot.dm_engine import DMEngine
from backend.bot.account_pool import AccountPool
from backend.bot.ig_client import is_french_holiday
from backend.database import async_session
from backend.models import IgAccount, Message, Niche, Prospect, SystemLog, Tenant

logger = logging.getLogger("instafarm.scheduler")

PARIS_TZ = pytz.timezone("Europe/Paris")

# Jours feries francais fixes (mois, jour)
JOURS_FERIES = [
    (1, 1),    # Jour de l'An
    (5, 1),    # Fete du Travail
    (5, 8),    # Victoire 1945
    (7, 14),   # Fete nationale
    (8, 15),   # Assomption
    (11, 1),   # Toussaint
    (11, 11),  # Armistice
    (12, 25),  # Noel
]

# Timeout par niche (5 min) — une niche bloquee ne bloque pas les autres
NICHE_TIMEOUT_SECONDS = 300.0


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id, level=level, module="scheduler",
            message=message, details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


def check_active_hours() -> bool:
    """
    Verifie si on est entre 09h00 et 20h00 heure de Paris.
    Verifie si ce n'est pas un jour ferie (fixes + variables).
    """
    now_paris = datetime.now(PARIS_TZ)

    # Heures actives
    if not (9 <= now_paris.hour < 20):
        return False

    # Jours feries fixes
    if (now_paris.month, now_paris.day) in JOURS_FERIES:
        return False

    # Jours feries variables (Paques, Ascension, Pentecote)
    if is_french_holiday(now_paris):
        return False

    return True


def is_rest_day(rest_days: list[int] | None = None) -> bool:
    """Verifie si aujourd'hui est un jour de repos configure."""
    now_paris = datetime.now(PARIS_TZ)
    weekday = now_paris.weekday()  # 0=lundi, 6=dimanche

    if rest_days and weekday in rest_days:
        return True
    return False


async def get_active_niches(tenant_id: int) -> list[Niche]:
    """Recupere toutes les niches actives d'un tenant."""
    async with async_session() as session:
        result = await session.execute(
            select(Niche)
            .where(Niche.tenant_id == tenant_id, Niche.status == "active")
        )
        return list(result.scalars().all())


class InstaFarmScheduler:
    """L'orchestrateur principal. asyncio.gather pour VRAI parallelisme."""

    def __init__(self):
        self.dm_engine = DMEngine()
        self.anti_ban = AntiBanEngine()
        self.pool = AccountPool()

    async def process_all_niches(self, tenant_id: int):
        """Lance TOUTES les niches en parallele avec timeout individuel."""
        if not check_active_hours():
            return

        niches = await get_active_niches(tenant_id)
        if not niches:
            return

        async def _wrap_with_timeout(niche, idx):
            """Timeout individuel — une niche bloquee ne bloque pas les autres."""
            try:
                return await asyncio.wait_for(
                    self._process_single_niche(niche, tenant_id),
                    timeout=NICHE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await _log(tenant_id, "ERROR", f"Niche {niche.name} timeout apres {NICHE_TIMEOUT_SECONDS}s")
                return None
            except Exception as e:
                await _log(tenant_id, "ERROR", f"Niche {niche.name} erreur: {e}")
                return None

        tasks = [_wrap_with_timeout(niche, i) for i, niche in enumerate(niches)]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        success_count = sum(1 for r in results if r is not None)
        logger.info(f"[scheduler] {success_count}/{len(niches)} niches traitees")

    async def _process_single_niche(self, niche: Niche, tenant_id: int):
        """
        Pour une niche :
        1. Follow les meilleurs prospects 'scored'
        2. Envoie DMs aux prospects 'follow_back'
        3. Traite les relances due
        """
        try:
            # 1. Follow queue
            await self.dm_engine.process_follow_queue(niche, tenant_id)

            # 2. DM queue
            await self.dm_engine.process_niche_dm_queue(niche, tenant_id)

            # 3. Relances
            await self.dm_engine.process_relances(tenant_id)

            await _log(tenant_id, "INFO", f"Niche {niche.name} traitee avec succes")

        except Exception as e:
            await _log(tenant_id, "ERROR", f"Erreur niche {niche.name}: {e}")
            raise

    async def check_follow_backs_all(self, tenant_id: int):
        """Verifie les follow-backs pour tous les tenants."""
        await self.dm_engine.check_follow_backs(tenant_id)

    async def check_anti_ban_all(self, tenant_id: int):
        """Lance le check anti-ban sur tous les comptes actifs."""
        await self.anti_ban.check_all_accounts(tenant_id)

    async def daily_maintenance(self, tenant_id: int):
        """Maintenance quotidienne a 06h00."""
        # Reset quotas journaliers
        await self.pool.reset_daily_quotas()

        # Verifier si des niches ont besoin de nouveaux comptes
        needs_replenishment = await self.pool.check_replenishment_needed(tenant_id)
        if needs_replenishment:
            await _log(
                tenant_id, "WARNING",
                f"Niches qui ont besoin de nouveaux comptes: {needs_replenishment}",
            )

    async def send_morning_report(self, tenant_id: int) -> str:
        """
        Push notification a 08h00.
        Genere le rapport avec les stats de la nuit.
        """
        now = datetime.utcnow()
        yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0)

        async with async_session() as session:
            # Follows du jour precedent
            follows_result = await session.execute(
                select(func.count(Prospect.id))
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.followed_at.isnot(None),
                    Prospect.followed_at >= yesterday,
                )
            )
            follows_count = follows_result.scalar() or 0

            # DMs envoyes
            dms_result = await session.execute(
                select(func.count(Message.id))
                .where(
                    Message.tenant_id == tenant_id,
                    Message.direction == "outbound",
                    Message.sent_at.isnot(None),
                    Message.sent_at >= yesterday,
                )
            )
            dms_count = dms_result.scalar() or 0

            # Reponses recues
            replies_result = await session.execute(
                select(func.count(Message.id))
                .where(
                    Message.tenant_id == tenant_id,
                    Message.direction == "inbound",
                    Message.created_at >= yesterday,
                )
            )
            replies_count = replies_result.scalar() or 0

            # Prospects chauds (interested)
            hot_result = await session.execute(
                select(func.count(Prospect.id))
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "interested",
                    Prospect.last_reply_at.isnot(None),
                    Prospect.last_reply_at >= yesterday,
                )
            )
            hot_count = hot_result.scalar() or 0

            # Top prospect
            top_result = await session.execute(
                select(Prospect.username)
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "interested",
                )
                .order_by(Prospect.score.desc())
                .limit(1)
            )
            top_prospect = top_result.scalar_one_or_none() or "aucun"

        report = (
            f"Nuit: {follows_count} follows, {dms_count} DMs, "
            f"{replies_count} reponses, {hot_count} chauds\n"
            f"Top prospect: @{top_prospect}"
        )

        await _log(tenant_id, "INFO", f"Rapport matin: {report}")
        return report

    def setup_jobs(self):
        """
        Configure tous les jobs recurrents avec APScheduler.
        Appele au demarrage du bot.
        """
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            scheduler = AsyncIOScheduler(timezone=PARIS_TZ)

            # Toutes les heures (09h-20h) : process niches
            scheduler.add_job(
                self.process_all_niches,
                CronTrigger(hour="9-19", minute=0),
                args=[1],  # tenant_id=1 pour solo
                id="process_niches",
            )

            # Toutes les heures : check follow-backs + anti-ban
            scheduler.add_job(
                self.check_follow_backs_all,
                CronTrigger(hour="9-20", minute=30),
                args=[1],
                id="check_follow_backs",
            )
            scheduler.add_job(
                self.check_anti_ban_all,
                CronTrigger(hour="9-20", minute=45),
                args=[1],
                id="check_anti_ban",
            )

            # Tous les jours a 06h00 : maintenance
            scheduler.add_job(
                self.daily_maintenance,
                CronTrigger(hour=6, minute=0),
                args=[1],
                id="daily_maintenance",
            )

            # Tous les jours a 08h00 : rapport matin
            scheduler.add_job(
                self.send_morning_report,
                CronTrigger(hour=8, minute=0),
                args=[1],
                id="morning_report",
            )

            scheduler.start()
            return scheduler

        except ImportError:
            # APScheduler non installe — mode dev sans scheduler
            return None
