"""Abstraction Instagram : instagrapi (Phase 1) / HikerAPI (Phase 2)."""

import asyncio
import json
import os
import random
from datetime import datetime, timedelta

import pytz
from sqlalchemy import select, update

from backend.database import async_session
from backend.models import IgAccount, SystemLog

PARIS_TZ = pytz.timezone("Europe/Paris")

# Quotas max par age de compte (depuis CLAUDE.md)
QUOTAS = {
    "warmup_0_7":   {"follows": 5,  "dms": 0,  "likes": 10},
    "warmup_7_14":  {"follows": 10, "dms": 3,  "likes": 20},
    "warmup_14_18": {"follows": 15, "dms": 8,  "likes": 30},
    "active_young": {"follows": 20, "dms": 12, "likes": 50},   # 18-30j
    "active_mid":   {"follows": 30, "dms": 15, "likes": 60},   # 30-90j
    "active_old":   {"follows": 40, "dms": 20, "likes": 80},   # >90j
}

# Jours feries fixes francais (mois, jour)
FIXED_HOLIDAYS = {
    (1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25),
}

# Jours feries variables 2025-2027 (Paques, Ascension, Pentecote)
VARIABLE_HOLIDAYS = {
    "2025-04-21", "2025-05-29", "2025-06-09",
    "2026-04-06", "2026-05-14", "2026-05-25",
    "2027-03-29", "2027-05-06", "2027-05-17",
}


async def human_delay(
    min_minutes: float = 8.0,
    max_minutes: float = 20.0,
    account_personality: dict | None = None,
):
    """
    Delai humain realiste entre deux actions Instagram.
    JAMAIS moins de 8 minutes. Distribution beta (pas uniforme).
    Respecte la personnalite du compte.
    """
    if account_personality:
        min_minutes = account_personality.get("pause_min", min_minutes)
        max_minutes = account_personality.get("pause_max", max_minutes)

    # Distribution beta centree sur le milieu (evite les patterns reguliers)
    beta_sample = random.betavariate(2, 2)
    delay_seconds = (min_minutes + beta_sample * (max_minutes - min_minutes)) * 60

    # Micro-variations +/- 30s
    delay_seconds += random.uniform(-30, 30)
    delay_seconds = max(delay_seconds, min_minutes * 60)

    await asyncio.sleep(delay_seconds)


def is_french_holiday(date: datetime | None = None) -> bool:
    """Verifie si la date est un jour ferie francais (fixes + variables)."""
    if date is None:
        date = datetime.now(PARIS_TZ)
    if (date.month, date.day) in FIXED_HOLIDAYS:
        return True
    return date.strftime("%Y-%m-%d") in VARIABLE_HOLIDAYS


def is_active_hours(account_personality: dict | None = None) -> bool:
    """
    Retourne True si on est dans la plage horaire active.
    Defaut : 09h00-20h00 Paris. Respecte personnalite + jours feries + rest days.
    """
    now_paris = datetime.now(PARIS_TZ)

    wake_hour = 9
    sleep_hour = 20
    if account_personality:
        wake_hour = account_personality.get("wake_hour", 9)
        sleep_hour = account_personality.get("sleep_hour", 20)

    # Jours feries
    if is_french_holiday(now_paris):
        return False

    # Jours de repos du compte
    rest_days = account_personality.get("rest_days", [6]) if account_personality else [6]
    if now_paris.weekday() in rest_days:
        return False

    return wake_hour <= now_paris.hour < sleep_hour


def get_account_age_days(account: IgAccount) -> int:
    """Nombre de jours depuis la creation du compte."""
    if not account.created_at:
        return 0
    delta = datetime.utcnow() - account.created_at
    return delta.days


def get_quota_tier(account: IgAccount) -> str:
    """Determine le tier de quota selon l'age du compte."""
    days = get_account_age_days(account)
    if days < 7:
        return "warmup_0_7"
    if days < 14:
        return "warmup_7_14"
    if days < 18:
        return "warmup_14_18"
    if days < 30:
        return "active_young"
    if days < 90:
        return "active_mid"
    return "active_old"


def check_quota(account: IgAccount, action: str) -> bool:
    """Verifie si le quota n'est pas atteint pour l'action donnee."""
    tier = get_quota_tier(account)
    limits = QUOTAS[tier]

    if action == "follow":
        return account.follows_today < limits["follows"]
    if action == "dm":
        return account.dms_today < limits["dms"]
    if action == "like":
        return account.likes_today < limits["likes"]
    return False


async def _log_action(tenant_id: int, level: str, module: str, message: str, details: dict | None = None):
    """Log une action en DB."""
    async with async_session() as session:
        log = SystemLog(
            tenant_id=tenant_id,
            level=level,
            module=module,
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(log)
        await session.commit()


async def _increment_counter(account_id: int, field: str):
    """Incremente un compteur journalier + total sur le compte."""
    total_field = f"total_{field.replace('_today', '')}" if "_today" in field else None
    async with async_session() as session:
        account = await session.get(IgAccount, account_id)
        if not account:
            return
        current = getattr(account, field, 0)
        setattr(account, field, current + 1)
        if total_field and hasattr(account, total_field):
            total = getattr(account, total_field, 0)
            setattr(account, total_field, total + 1)
        account.last_action = datetime.utcnow()
        await session.commit()


class IGClient:
    """Abstraction Instagram. Phase 1 = instagrapi, Phase 2 = HikerAPI."""

    def __init__(self):
        self._clients: dict[int, object] = {}  # account_id -> instagrapi.Client

    async def login(self, account: IgAccount) -> bool:
        """Login et sauvegarde la session JSON en DB."""
        if not is_active_hours():
            await _log_action(account.tenant_id, "WARNING", "ig_client", f"Login refuse hors heures actives pour @{account.username}")
            return False

        try:
            if account.ig_driver == "hikerapi":
                return await self._login_hikerapi(account)
            return await self._login_instagrapi(account)
        except Exception as e:
            await _log_action(
                account.tenant_id, "ERROR", "ig_client",
                f"Login echoue pour @{account.username}: {e}",
                {"error": str(e)},
            )
            return False

    async def _login_instagrapi(self, account: IgAccount) -> bool:
        """Login via instagrapi."""
        from instagrapi import Client

        cl = Client()

        # Configurer proxy si disponible
        if account.proxy:
            proxy_url = f"http://{account.proxy.username}:{account.proxy.password}@{account.proxy.host}:{account.proxy.port}"
            cl.set_proxy(proxy_url)

        # Configurer fingerprint
        if account.device_id:
            cl.set_device({"device_id": account.device_id})
        if account.user_agent:
            cl.set_user_agent(account.user_agent)

        # Charger session existante si disponible
        if account.session_data:
            try:
                settings = json.loads(account.session_data)
                cl.set_settings(settings)
                cl.login(account.username, account.password)
            except Exception:
                cl.login(account.username, account.password)
        else:
            cl.login(account.username, account.password)

        # Sauvegarder session en DB
        session_data = json.dumps(cl.get_settings(), ensure_ascii=False)
        async with async_session() as db:
            await db.execute(
                update(IgAccount)
                .where(IgAccount.id == account.id)
                .values(session_data=session_data, last_login=datetime.utcnow())
            )
            await db.commit()

        self._clients[account.id] = cl
        await _log_action(account.tenant_id, "INFO", "ig_client", f"Login OK pour @{account.username}")
        return True

    async def _login_hikerapi(self, account: IgAccount) -> bool:
        """Login via HikerAPI (Phase 2)."""
        import httpx

        endpoint = os.getenv("HIKERAPI_ENDPOINT", "https://api.hikerapi.com/v1")
        key = os.getenv("HIKERAPI_KEY", "")
        if not key:
            raise ValueError("HIKERAPI_KEY non defini")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{endpoint}/auth/login",
                json={"username": account.username, "password": account.password},
                headers={"Authorization": f"Bearer {key}"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        async with async_session() as db:
            await db.execute(
                update(IgAccount)
                .where(IgAccount.id == account.id)
                .values(session_data=json.dumps(data), last_login=datetime.utcnow())
            )
            await db.commit()

        await _log_action(account.tenant_id, "INFO", "ig_client", f"HikerAPI login OK pour @{account.username}")
        return True

    async def follow(self, account: IgAccount, target_username: str) -> bool:
        """Follow avec human_delay avant l'action."""
        if not is_active_hours():
            return False
        if not check_quota(account, "follow"):
            await _log_action(account.tenant_id, "WARNING", "ig_client", f"Quota follow atteint pour @{account.username}")
            return False

        await human_delay()

        try:
            if account.ig_driver == "instagrapi":
                cl = self._clients.get(account.id)
                if not cl:
                    return False
                user_id = cl.user_id_from_username(target_username)
                cl.user_follow(user_id)
            else:
                # HikerAPI
                import httpx
                endpoint = os.getenv("HIKERAPI_ENDPOINT")
                key = os.getenv("HIKERAPI_KEY")
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{endpoint}/user/follow",
                        json={"username": target_username},
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30,
                    )

            await _increment_counter(account.id, "follows_today")
            await _log_action(account.tenant_id, "INFO", "ig_client", f"@{account.username} a follow @{target_username}")
            return True

        except Exception as e:
            await _log_action(
                account.tenant_id, "ERROR", "ig_client",
                f"Follow echoue @{account.username} → @{target_username}: {e}",
                {"error": str(e)},
            )
            return False

    async def send_dm(self, account: IgAccount, username: str, text: str) -> dict:
        """Envoie DM. Retourne {"success": bool, "message_id": str, "error": str}."""
        if not is_active_hours():
            return {"success": False, "message_id": "", "error": "Hors heures actives"}
        if not check_quota(account, "dm"):
            return {"success": False, "message_id": "", "error": "Quota DM atteint"}

        await human_delay()

        try:
            if account.ig_driver == "instagrapi":
                cl = self._clients.get(account.id)
                if not cl:
                    return {"success": False, "message_id": "", "error": "Client non connecte"}
                user_id = cl.user_id_from_username(username)
                result = cl.direct_send(text, [int(user_id)])
                message_id = str(result.id) if result else ""
            else:
                import httpx
                endpoint = os.getenv("HIKERAPI_ENDPOINT")
                key = os.getenv("HIKERAPI_KEY")
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{endpoint}/dm/send",
                        json={"username": username, "text": text},
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30,
                    )
                    data = resp.json()
                    message_id = data.get("message_id", "")

            await _increment_counter(account.id, "dms_today")
            await _log_action(account.tenant_id, "INFO", "ig_client", f"DM envoye par @{account.username} a @{username}")
            return {"success": True, "message_id": message_id, "error": ""}

        except Exception as e:
            await _log_action(
                account.tenant_id, "ERROR", "ig_client",
                f"DM echoue @{account.username} → @{username}: {e}",
                {"error": str(e)},
            )
            return {"success": False, "message_id": "", "error": str(e)}

    async def get_user_info(self, account: IgAccount, username: str) -> dict:
        """Recupere info profil (followers, bio, posts, etc.)."""
        try:
            if account.ig_driver == "instagrapi":
                cl = self._clients.get(account.id)
                if not cl:
                    return {}
                info = cl.user_info_by_username(username)
                return {
                    "instagram_id": str(info.pk),
                    "username": info.username,
                    "full_name": info.full_name,
                    "bio": info.biography,
                    "followers": info.follower_count,
                    "following": info.following_count,
                    "posts_count": info.media_count,
                    "has_link_in_bio": bool(info.external_url),
                    "profile_pic_url": str(info.profile_pic_url),
                }
            else:
                import httpx
                endpoint = os.getenv("HIKERAPI_ENDPOINT")
                key = os.getenv("HIKERAPI_KEY")
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{endpoint}/user/info/{username}",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30,
                    )
                    return resp.json()

        except Exception as e:
            await _log_action(
                account.tenant_id, "ERROR", "ig_client",
                f"get_user_info echoue pour @{username}: {e}",
            )
            return {}

    async def like_post(self, account: IgAccount, media_id: str) -> bool:
        """Like un post."""
        if not is_active_hours():
            return False
        if not check_quota(account, "like"):
            return False

        await human_delay()

        try:
            if account.ig_driver == "instagrapi":
                cl = self._clients.get(account.id)
                if not cl:
                    return False
                cl.media_like(int(media_id))
            else:
                import httpx
                endpoint = os.getenv("HIKERAPI_ENDPOINT")
                key = os.getenv("HIKERAPI_KEY")
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{endpoint}/media/like",
                        json={"media_id": media_id},
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30,
                    )

            await _increment_counter(account.id, "likes_today")
            await _log_action(account.tenant_id, "INFO", "ig_client", f"@{account.username} a like media {media_id}")
            return True

        except Exception as e:
            await _log_action(
                account.tenant_id, "ERROR", "ig_client",
                f"Like echoue @{account.username} media {media_id}: {e}",
            )
            return False

    async def check_session_valid(self, account: IgAccount) -> bool:
        """Verifie si la session est encore valide."""
        try:
            if account.ig_driver == "instagrapi":
                cl = self._clients.get(account.id)
                if not cl:
                    return False
                cl.get_timeline_feed()
                return True
            else:
                import httpx
                endpoint = os.getenv("HIKERAPI_ENDPOINT")
                key = os.getenv("HIKERAPI_KEY")
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{endpoint}/auth/check",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=10,
                    )
                    return resp.status_code == 200
        except Exception:
            return False
