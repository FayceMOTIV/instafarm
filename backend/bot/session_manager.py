"""Gestion de la persistance des sessions Instagram en DB."""

import json
import os
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update

from backend.database import async_session
from backend.models import IgAccount, SystemLog


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="session_manager",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


class SessionManager:
    """Gere la persistance des sessions Instagram en DB."""

    async def save_session(self, account_id: int, session_data: dict) -> bool:
        """
        Sauvegarde correcte d'une session instagrapi en DB.
        Nettoie les donnees non-serialisables avant sauvegarde.
        """
        try:
            # Nettoyer les donnees non-serialisables
            clean = {
                k: v for k, v in session_data.items()
                if isinstance(v, (str, int, float, bool, list, dict, type(None)))
            }
            session_json = json.dumps(clean, ensure_ascii=False)

            async with async_session() as session:
                await session.execute(
                    update(IgAccount)
                    .where(IgAccount.id == account_id)
                    .values(
                        session_data=session_json,
                        last_login=datetime.utcnow(),
                    )
                )
                await session.commit()
            return True
        except Exception as e:
            await _log(0, "ERROR", f"Erreur sauvegarde session account_id={account_id}: {e}")
            return False

    async def load_session(self, account_id: int) -> dict | None:
        """Charge session depuis DB."""
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount.session_data).where(IgAccount.id == account_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            try:
                return json.loads(row)
            except (json.JSONDecodeError, TypeError):
                return None

    async def save_instagrapi_session(self, account_id: int, cl) -> bool:
        """
        Sauvegarde une session instagrapi via cl.get_settings().
        IMPORTANT : Ne jamais sauvegarder cl.cookie_jar directement.
        """
        try:
            settings = cl.get_settings()
            return await self.save_session(account_id, settings)
        except Exception as e:
            await _log(0, "ERROR", f"Erreur get_settings account_id={account_id}: {e}")
            return False

    async def load_instagrapi_session(self, account_id: int, cl) -> bool:
        """
        Charge une session instagrapi depuis DB.
        Verifie que la session est encore valide. Re-login si expiree.
        """
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount).where(IgAccount.id == account_id)
            )
            account = result.scalar_one_or_none()

        if not account or not account.session_data:
            return False

        try:
            settings = json.loads(account.session_data)
            cl.set_settings(settings)
            cl.username = account.username

            # Appel leger pour valider la session
            try:
                user_id = cl.user_id_from_username(account.username)
                if user_id:
                    return True
            except Exception:
                pass

            # Session expiree → re-login
            try:
                cl.login(account.username, account.password)
                await self.save_instagrapi_session(account_id, cl)
                return True
            except Exception as login_err:
                await _log(
                    account.tenant_id, "ERROR",
                    f"Re-login echoue pour @{account.username}: {login_err}",
                )
                return False

        except Exception as e:
            await _log(0, "ERROR", f"Erreur chargement session account_id={account_id}: {e}")
            return False

    async def resolve_challenge(self, account: IgAccount, challenge_type: str) -> str:
        """
        Resout les challenges Instagram.
        - sms : contacte SMS-activate pour recuperer le code
        - email : non implemente en Phase 1
        - selfie / video : impossible → alerte + pause compte
        """
        if challenge_type in ("selfie", "video"):
            # Suspendre le compte immediatement
            async with async_session() as session:
                await session.execute(
                    update(IgAccount)
                    .where(IgAccount.id == account.id)
                    .values(status="suspended")
                )
                await session.commit()

            await _log(
                account.tenant_id, "CRITICAL",
                f"Compte @{account.username} suspendu — challenge {challenge_type} non resolvable automatiquement",
                {"challenge_type": challenge_type, "account_id": account.id},
            )
            return ""

        if challenge_type == "sms":
            return await self._resolve_sms_challenge(account)

        await _log(
            account.tenant_id, "WARNING",
            f"Challenge type inconnu: {challenge_type} pour @{account.username}",
        )
        return ""

    async def _resolve_sms_challenge(self, account: IgAccount) -> str:
        """Recupere le code SMS via SMS-activate."""
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")
        if not sms_key:
            await _log(account.tenant_id, "ERROR", "SMS_ACTIVATE_KEY non defini")
            return ""

        # On suppose qu'on a l'activation_id stocke quelque part
        # En Phase 1, on utilise le phone du compte
        if not account.phone:
            await _log(account.tenant_id, "ERROR", f"Pas de phone pour @{account.username}")
            return ""

        try:
            async with httpx.AsyncClient() as client:
                # Demander un nouveau numero si besoin
                resp = await client.get(
                    "https://api.sms-activate.org/stubs/handler_api.php",
                    params={
                        "api_key": sms_key,
                        "action": "getStatus",
                        "id": account.phone,  # activation_id
                    },
                    timeout=30,
                )
                text = resp.text
                if "STATUS_OK" in text:
                    code = text.split(":")[1]
                    await _log(account.tenant_id, "INFO", f"Code SMS recu pour @{account.username}: {code}")
                    return code
                return ""
        except Exception as e:
            await _log(account.tenant_id, "ERROR", f"SMS challenge echoue: {e}")
            return ""

    async def refresh_session_if_needed(self, account: IgAccount) -> bool:
        """Re-login si session > 7 jours ou invalide."""
        if not account.last_login:
            return True  # Besoin de login

        age = datetime.utcnow() - account.last_login
        if age > timedelta(days=7):
            await _log(
                account.tenant_id, "INFO",
                f"Session expiree pour @{account.username} (age: {age.days}j), re-login necessaire",
            )
            return True  # Besoin de re-login

        return False  # Session encore valide
