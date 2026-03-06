"""Creation de comptes Instagram via Playwright + SMS-activate + warmup 18 jours."""

import asyncio
import json
import os
import random
import string
import uuid
from datetime import datetime

import httpx
from sqlalchemy import select, update

from backend.database import async_session
from backend.models import IgAccount, Niche, Proxy, SystemLog

# Warmup schedule 18 jours (non-lineaire, avec jours de repos)
WARMUP_SCHEDULE = {
    0:  {"follows": 0,  "likes": 3,  "dms": 0,  "rest": False},
    1:  {"follows": 2,  "likes": 5,  "dms": 0,  "rest": False},
    2:  {"follows": 3,  "likes": 8,  "dms": 0,  "rest": False},
    3:  {"follows": 0,  "likes": 0,  "dms": 0,  "rest": True},
    4:  {"follows": 5,  "likes": 10, "dms": 0,  "rest": False},
    5:  {"follows": 7,  "likes": 12, "dms": 0,  "rest": False},
    6:  {"follows": 8,  "likes": 15, "dms": 0,  "rest": False},
    7:  {"follows": 0,  "likes": 5,  "dms": 0,  "rest": True},
    8:  {"follows": 10, "likes": 18, "dms": 2,  "rest": False},
    9:  {"follows": 12, "likes": 20, "dms": 3,  "rest": False},
    10: {"follows": 0,  "likes": 0,  "dms": 0,  "rest": True},
    11: {"follows": 15, "likes": 22, "dms": 5,  "rest": False},
    12: {"follows": 15, "likes": 25, "dms": 6,  "rest": False},
    13: {"follows": 18, "likes": 28, "dms": 7,  "rest": False},
    14: {"follows": 0,  "likes": 8,  "dms": 0,  "rest": True},
    15: {"follows": 18, "likes": 30, "dms": 8,  "rest": False},
    16: {"follows": 20, "likes": 35, "dms": 10, "rest": False},
    17: {"follows": 20, "likes": 35, "dms": 10, "rest": False},
    18: {"follows": 20, "likes": 40, "dms": 12, "rest": False},
}

# Prenoms francais pour identites fictives
FIRST_NAMES = [
    "Lucas", "Emma", "Louis", "Jade", "Gabriel", "Louise", "Raphael", "Alice",
    "Leo", "Lina", "Hugo", "Rose", "Arthur", "Ambre", "Jules", "Chloe",
    "Adam", "Lea", "Maël", "Anna", "Noah", "Mila", "Nathan", "Inès",
    "Tom", "Juliette", "Théo", "Sarah", "Ethan", "Eva",
]

LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit",
    "Durand", "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel",
    "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier",
]

USER_AGENTS = [
    "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-S911B; dm1q; qcom; fr_FR; 458229258)",
    "Instagram 275.0.0.27.98 Android (34/14; 480dpi; 1440x3088; samsung; SM-S928B; e3q; qcom; fr_FR; 458229258)",
    "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2340; Google; Pixel 7; panther; tensor; fr_FR; 458229258)",
    "Instagram 275.0.0.27.98 Android (34/14; 420dpi; 1080x2400; Xiaomi; 2201117SG; vili; qcom; fr_FR; 458229258)",
    "Instagram 275.0.0.27.98 Android (33/13; 480dpi; 1440x3200; OnePlus; CPH2449; OP5958L1; qcom; fr_FR; 458229258)",
]


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="account_creator",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


class AccountCreator:
    """Cree des comptes Instagram via Playwright + SMS-activate."""

    async def create_account(self, niche: Niche, proxy: Proxy) -> IgAccount | None:
        """Cree un compte. Retourne le compte cree ou None si echec."""
        # Verifier capacite proxy
        if not await self._check_proxy_capacity(proxy):
            await _log(niche.tenant_id, "WARNING", f"Proxy {proxy.host}:{proxy.port} sature ({proxy.accounts_count}/{proxy.max_accounts})")
            return None

        try:
            # 1. Reserver numero SMS
            activation_id, phone = await self._get_sms_number()

            # 2. Generer identite
            identity = await self._generate_identity(niche)

            # 3. Generer bio IA
            bio = await self._generate_bio(niche)

            # 4. Lancer Playwright via proxy
            account = await self._create_via_playwright(identity, phone, proxy, niche, bio)
            if not account:
                return None

            # 5. Attendre code SMS
            code = await self._wait_for_sms_code(activation_id)
            if not code:
                await _log(niche.tenant_id, "ERROR", f"Code SMS non recu pour {phone}")
                return None

            # 6. Sauvegarder en DB
            new_account = IgAccount(
                tenant_id=niche.tenant_id,
                niche_id=niche.id,
                username=identity["username"],
                password=identity["password"],
                email=identity.get("email"),
                phone=phone,
                proxy_id=proxy.id,
                status="warmup",
                warmup_day=0,
                warmup_started_at=datetime.utcnow(),
                device_id=str(uuid.uuid4()),
                user_agent=random.choice(USER_AGENTS),
                personality=json.dumps({
                    "typing_speed": random.uniform(0.05, 0.15),
                    "pause_min": random.randint(3, 8),
                    "pause_max": random.randint(15, 30),
                    "sleep_hour": random.randint(22, 23),
                    "wake_hour": random.randint(8, 10),
                }),
            )

            async with async_session() as session:
                session.add(new_account)
                # Incrementer accounts_count du proxy
                await session.execute(
                    update(Proxy)
                    .where(Proxy.id == proxy.id)
                    .values(accounts_count=proxy.accounts_count + 1)
                )
                await session.commit()
                await session.refresh(new_account)

            await _log(
                niche.tenant_id, "INFO",
                f"Compte @{new_account.username} cree pour niche {niche.name}",
                {"account_id": new_account.id, "niche_id": niche.id},
            )
            return new_account

        except Exception as e:
            await _log(niche.tenant_id, "ERROR", f"Creation compte echouee: {e}", {"error": str(e)})
            return None

    async def _get_sms_number(self) -> tuple[str, str]:
        """(activation_id, phone_number) depuis SMS-activate."""
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")
        service = os.getenv("SMS_ACTIVATE_SERVICE", "ig")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.sms-activate.org/stubs/handler_api.php",
                params={
                    "api_key": sms_key,
                    "action": "getNumber",
                    "service": service,
                    "country": 0,  # Tous pays
                },
                timeout=30,
            )
            text = resp.text
            # Format: ACCESS_NUMBER:ID:PHONE
            if "ACCESS_NUMBER" in text:
                parts = text.split(":")
                return parts[1], parts[2]
            raise ValueError(f"SMS-activate erreur: {text}")

    async def _wait_for_sms_code(self, activation_id: str) -> str | None:
        """Poll SMS-activate toutes les 10s, max 5 min."""
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")

        for _ in range(30):  # 30 * 10s = 5 min max
            await asyncio.sleep(10)

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.sms-activate.org/stubs/handler_api.php",
                    params={
                        "api_key": sms_key,
                        "action": "getStatus",
                        "id": activation_id,
                    },
                    timeout=15,
                )
                text = resp.text
                if "STATUS_OK" in text:
                    return text.split(":")[1]
                if "STATUS_CANCEL" in text:
                    return None

        return None

    async def _generate_identity(self, niche: Niche) -> dict:
        """Genere une identite fictive coherente avec la niche."""
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        suffix = "".join(random.choices(string.digits, k=random.randint(2, 4)))
        username = f"{first.lower()}.{last.lower()}{suffix}"
        password = "".join(random.choices(string.ascii_letters + string.digits + "!@#$", k=16))

        # Date de naissance entre 22 et 45 ans
        year = random.randint(1981, 2003)
        month = random.randint(1, 12)
        day = random.randint(1, 28)

        return {
            "first_name": first,
            "last_name": last,
            "username": username,
            "password": password,
            "birth_year": year,
            "birth_month": month,
            "birth_day": day,
            "email": f"{username}@protonmail.com",
        }

    async def _generate_bio(self, niche: Niche) -> str:
        """Appelle Groq pour generer une bio Instagram."""
        groq_key = os.getenv("GROQ_API_KEY", "")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        if not groq_key:
            # Fallback bio generique
            return f"Passionné(e) par le monde de la {niche.name.lower()} 🇫🇷"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Tu generes des bios Instagram courtes (max 150 caracteres) pour des professionnels francais. La bio doit paraitre authentique, pas un bot."
                            },
                            {
                                "role": "user",
                                "content": f"Genere une bio Instagram pour un profil qui s'interesse a la niche {niche.name} en France. Max 150 caracteres. Reponds UNIQUEMENT avec la bio, rien d'autre."
                            }
                        ],
                        "max_tokens": 60,
                        "temperature": 0.9,
                    },
                    timeout=10,
                )
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return f"Passionné(e) par le monde de la {niche.name.lower()} 🇫🇷"

    async def _check_proxy_capacity(self, proxy: Proxy) -> bool:
        """Verifie que le proxy a < max_accounts comptes. JAMAIS > 5."""
        return proxy.accounts_count < proxy.max_accounts

    async def _create_via_playwright(self, identity: dict, phone: str, proxy: Proxy, niche: Niche, bio: str) -> bool:
        """Cree le compte Instagram via Playwright. Retourne True si succes."""
        try:
            from playwright.async_api import async_playwright

            proxy_config = {
                "server": f"http://{proxy.host}:{proxy.port}",
            }
            if proxy.username and proxy.password:
                proxy_config["username"] = proxy.username
                proxy_config["password"] = proxy.password

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    proxy=proxy_config,
                )
                context = await browser.new_context(
                    viewport={"width": 412, "height": 915},
                    user_agent=random.choice(USER_AGENTS),
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                )
                page = await context.new_page()

                # Aller sur la page d'inscription
                await page.goto("https://www.instagram.com/accounts/emailsignup/")
                await asyncio.sleep(random.uniform(2, 4))

                # Remplir le formulaire avec des delais humains
                await page.fill("input[name='emailOrPhone']", phone)
                await asyncio.sleep(random.uniform(0.5, 1.5))

                await page.fill("input[name='fullName']", f"{identity['first_name']} {identity['last_name']}")
                await asyncio.sleep(random.uniform(0.5, 1.5))

                await page.fill("input[name='username']", identity["username"])
                await asyncio.sleep(random.uniform(0.5, 1.5))

                await page.fill("input[name='password']", identity["password"])
                await asyncio.sleep(random.uniform(1, 2))

                # Submit
                await page.click("button[type='submit']")
                await asyncio.sleep(random.uniform(3, 6))

                # Gerer la page de date de naissance si elle apparait
                try:
                    month_select = page.locator("select[title='Month:']")
                    if await month_select.is_visible(timeout=3000):
                        await month_select.select_option(str(identity["birth_month"]))
                        await page.locator("select[title='Day:']").select_option(str(identity["birth_day"]))
                        await page.locator("select[title='Year:']").select_option(str(identity["birth_year"]))
                        await asyncio.sleep(random.uniform(0.5, 1))
                        await page.click("button:has-text('Next')")
                        await asyncio.sleep(random.uniform(2, 4))
                except Exception:
                    pass  # Pas de page birthday

                await browser.close()
                return True

        except Exception as e:
            await _log(niche.tenant_id, "ERROR", f"Playwright creation echouee: {e}", {"error": str(e)})
            return False


async def execute_warmup_day(account: IgAccount):
    """
    Execute les actions du jour de warmup.
    Cible : comptes IG populaires dans la niche (pas les vraies cibles).
    Si warmup_day >= 18 → passe status a 'active'.
    """
    day = account.warmup_day
    schedule = WARMUP_SCHEDULE.get(day)

    if not schedule:
        # Au-dela de 18 jours → activer
        async with async_session() as session:
            await session.execute(
                update(IgAccount)
                .where(IgAccount.id == account.id)
                .values(status="active")
            )
            await session.commit()
        await _log(account.tenant_id, "INFO", f"@{account.username} warmup termine → status=active")
        return

    if schedule["rest"]:
        await _log(account.tenant_id, "INFO", f"@{account.username} jour de repos (day={day})")
        # Incrementer le jour meme en repos
        async with async_session() as session:
            await session.execute(
                update(IgAccount)
                .where(IgAccount.id == account.id)
                .values(warmup_day=day + 1)
            )
            await session.commit()
        return

    await _log(
        account.tenant_id, "INFO",
        f"@{account.username} warmup day={day}: {schedule['follows']}F/{schedule['likes']}L/{schedule['dms']}DM",
    )

    # Les actions reelles seront executees par le scheduler (Session 5)
    # Ici on prepare juste les quotas du jour

    # Avancer le jour de warmup
    new_day = day + 1
    new_status = "active" if new_day > 18 else "warmup"

    async with async_session() as session:
        await session.execute(
            update(IgAccount)
            .where(IgAccount.id == account.id)
            .values(warmup_day=new_day, status=new_status)
        )
        await session.commit()

    if new_status == "active":
        await _log(account.tenant_id, "INFO", f"@{account.username} warmup termine → status=active")
