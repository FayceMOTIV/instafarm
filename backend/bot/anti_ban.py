"""Detection ban/shadowban et auto-healing. Tourne toutes les heures."""

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select, update

from backend.database import async_session
from backend.models import IgAccount, Message, Prospect, SystemLog


class AccountHealthStatus(Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    SHADOWBANNED = "shadowbanned"
    ACTION_BLOCKED = "action_blocked"
    BANNED = "banned"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    status: AccountHealthStatus
    signals: dict
    recommendation: str
    auto_pause_hours: int = 0


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id, level=level, module="anti_ban",
            message=message, details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


class AntiBanEngine:
    """Detecte les signaux de ban/shadowban et reagit."""

    async def check_account_health(self, account: IgAccount) -> dict:
        """
        Verifie la sante d'un compte via detection multi-signal.
        Retourne status + signaux detectes + recommendation.
        """
        signals = {
            "follow_rate_low": False,
            "dm_delivery_low": False,
            "action_blocks_high": False,
            "already_banned": account.status == "banned",
        }

        # Signal 1 : follow-back rate < 2% sur 48h
        signals["follow_rate_low"] = await self._check_follow_rate(account)

        # Signal 2 : DM delivery rate < 50% sur 7 jours (shadowban DM)
        signals["dm_delivery_low"] = await self._check_dm_delivery_rate(account)

        # Signal 3 : > 3 action blocks cette semaine
        signals["action_blocks_high"] = account.action_blocks_week > 3

        # Decision finale
        critical_signals = sum([
            signals["already_banned"],
            account.action_blocks_week >= 5,
        ])

        warning_signals = sum([
            signals["follow_rate_low"],
            signals["dm_delivery_low"],
            signals["action_blocks_high"],
        ])

        if critical_signals >= 1 or signals["already_banned"]:
            status = "banned"
        elif warning_signals >= 2:
            status = "shadowbanned"
        elif warning_signals >= 1:
            status = "warning"
        else:
            status = "healthy"

        return {"status": status, "signals": signals}

    async def _check_follow_rate(self, account: IgAccount) -> bool:
        """Verifie si le follow-back rate est < 2% sur les 48 dernieres heures."""
        cutoff = datetime.utcnow() - timedelta(hours=48)

        async with async_session() as session:
            # Compter les follows faits par ce compte
            follows_result = await session.execute(
                select(func.count(Prospect.id))
                .where(
                    Prospect.tenant_id == account.tenant_id,
                    Prospect.status.in_(["followed", "follow_back", "dm_sent", "replied", "interested"]),
                    Prospect.followed_at.isnot(None),
                    Prospect.followed_at > cutoff,
                )
            )
            total_follows = follows_result.scalar() or 0

            if total_follows < 10:
                return False  # Pas assez de donnees

            # Compter les follow-backs
            follow_backs_result = await session.execute(
                select(func.count(Prospect.id))
                .where(
                    Prospect.tenant_id == account.tenant_id,
                    Prospect.status.in_(["follow_back", "dm_sent", "replied", "interested"]),
                    Prospect.follow_back_at.isnot(None),
                    Prospect.follow_back_at > cutoff,
                )
            )
            follow_backs = follow_backs_result.scalar() or 0

        rate = follow_backs / max(total_follows, 1)
        return rate < 0.02  # < 2%

    async def _check_dm_delivery_rate(self, account: IgAccount) -> bool:
        """
        Verifie si le DM delivery rate < 50% sur 7 jours.
        Plus robuste que zero-check : detecte les shadowbans partiels.
        """
        cutoff = datetime.utcnow() - timedelta(days=7)

        async with async_session() as session:
            # DMs delivered/read
            delivered_result = await session.execute(
                select(func.count(Message.id))
                .where(
                    Message.ig_account_id == account.id,
                    Message.direction == "outbound",
                    Message.status.in_(["delivered", "read"]),
                    Message.sent_at.isnot(None),
                    Message.sent_at > cutoff,
                )
            )
            delivered = delivered_result.scalar() or 0

            # Total DMs envoyes
            total_result = await session.execute(
                select(func.count(Message.id))
                .where(
                    Message.ig_account_id == account.id,
                    Message.direction == "outbound",
                    Message.sent_at.isnot(None),
                    Message.sent_at > cutoff,
                )
            )
            total_sent = total_result.scalar() or 0

        if total_sent < 5:
            return False  # Pas assez de donnees

        delivery_rate = delivered / total_sent
        return delivery_rate < 0.5  # < 50% = probable shadowban DM

    async def apply_healing(self, account: IgAccount, health: dict):
        """Actions selon le diagnostic."""
        status = health["status"]

        if status == "healthy":
            return

        if status == "warning":
            async with async_session() as session:
                await session.execute(
                    update(IgAccount)
                    .where(IgAccount.id == account.id)
                    .values(status="paused")
                )
                await session.commit()
            await _log(
                account.tenant_id, "WARNING",
                f"@{account.username} mis en pause 24h (warning signals)",
                health["signals"],
            )

        elif status == "shadowbanned":
            async with async_session() as session:
                await session.execute(
                    update(IgAccount)
                    .where(IgAccount.id == account.id)
                    .values(status="paused", session_data=None)
                )
                await session.commit()
            await _log(
                account.tenant_id, "WARNING",
                f"@{account.username} shadowban detecte — pause 48h + session reset",
                health["signals"],
            )

        elif status == "banned":
            async with async_session() as session:
                await session.execute(
                    update(IgAccount)
                    .where(IgAccount.id == account.id)
                    .values(
                        status="banned",
                        last_ban_at=datetime.utcnow(),
                        total_bans=account.total_bans + 1,
                    )
                )
                await session.commit()
            await _log(
                account.tenant_id, "CRITICAL",
                f"@{account.username} BANNI — remplacement necessaire",
                health["signals"],
            )

    async def check_all_accounts(self, tenant_id: int):
        """Verifie tous les comptes actifs d'un tenant."""
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount)
                .where(
                    IgAccount.tenant_id == tenant_id,
                    IgAccount.status.in_(["active", "warmup"]),
                )
            )
            accounts = result.scalars().all()

        for account in accounts:
            health = await self.check_account_health(account)
            if health["status"] != "healthy":
                await self.apply_healing(account, health)

    @staticmethod
    def generate_account_personality() -> dict:
        """Genere une 'personnalite' unique par compte."""
        typing_speeds = ["slow", "medium", "fast"]
        action_orders = [
            ["likes", "follows", "dms"],
            ["follows", "likes", "dms"],
            ["likes", "dms", "follows"],
        ]

        return {
            "typing_speed": random.choice(typing_speeds),
            "pause_min": random.randint(8, 12),
            "pause_max": random.randint(15, 25),
            "wake_hour": random.randint(8, 10),
            "sleep_hour": random.randint(19, 22),
            "rest_days": [random.choice([5, 6])],  # samedi ou dimanche
            "action_order": random.choice(action_orders),
        }
