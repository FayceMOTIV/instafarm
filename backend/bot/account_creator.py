"""Creation de comptes Instagram via Playwright + GrizzlySMS + CapSolver + warmup 18 jours."""

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


CAPSOLVER_API = "https://api.capsolver.com"
GRIZZLY_API = os.getenv("SMS_API_URL", "https://api.grizzlysms.com/stubs/handler_api.php")

# Mapping prefixe telephone → (code pays IG search term, prefixe a retirer)
# Utilise pour selectionner le bon pays dans le country picker Instagram
PHONE_PREFIX_MAP = {
    "33": ("France", "33"),
    "234": ("Nigeria", "234"),
    "62": ("Indonésie", "62"),
    "91": ("Inde", "91"),
    "44": ("Royaume-Uni", "44"),
    "1": ("États-Unis", "1"),
    "52": ("Mexique", "52"),
    "55": ("Brésil", "55"),
    "7": ("Russie", "7"),
    "84": ("Viêt Nam", "84"),
    "852": ("Hong Kong", "852"),
    "63": ("Philippines", "63"),
    "20": ("Égypte", "20"),
    "57": ("Colombie", "57"),
    "90": ("Turquie", "90"),
    "254": ("Kenya", "254"),
}

# Pays GrizzlySMS a essayer (ordre de preference)
# country_code → grizzly_country_id
SMS_COUNTRY_FALLBACKS = [78, 6, 19, 36, 10]


def _detect_phone_country(phone: str) -> tuple[str, str, str]:
    """Detecte le pays d'un numero et retourne (search_term, prefix, local_number).

    Returns:
        (search_term_for_ig, prefix, local_phone_number)
    """
    for prefix in sorted(PHONE_PREFIX_MAP.keys(), key=len, reverse=True):
        if phone.startswith(prefix):
            search_term, _ = PHONE_PREFIX_MAP[prefix]
            local = phone[len(prefix):]
            return search_term, prefix, local
    # Fallback: assume French
    return "France", "33", phone


class _TempMailClient:
    """Client mail.tm pour creer des emails temporaires et lire l'inbox."""

    API = "https://api.mail.tm"

    async def create_email(self) -> tuple[str, str, str]:
        """Cree un email temp. Retourne (email, password, token)."""
        async with httpx.AsyncClient(timeout=20) as client:
            # Get domain
            r = await client.get(f"{self.API}/domains")
            domains = r.json().get("hydra:member", [])
            if not domains:
                raise ValueError("mail.tm: aucun domaine disponible")
            domain = domains[0]["domain"]

            # Create account
            username = "if" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
            email = f"{username}@{domain}"
            pwd = "InstaFarm2026!" + "".join(random.choices(string.digits, k=4))

            r = await client.post(f"{self.API}/accounts", json={"address": email, "password": pwd})
            if r.status_code not in (200, 201):
                raise ValueError(f"mail.tm create error: {r.text[:100]}")

            # Get auth token
            r = await client.post(f"{self.API}/token", json={"address": email, "password": pwd})
            if r.status_code != 200:
                raise ValueError(f"mail.tm auth error: {r.text[:100]}")
            token = r.json()["token"]

            return email, pwd, token

    async def wait_for_code(self, token: str, max_wait: int = 300) -> str | None:
        """Poll l'inbox mail.tm pour trouver le code de verif Instagram.

        Retourne le code (6 chiffres) ou None si timeout.
        """
        import re

        async with httpx.AsyncClient(timeout=20) as client:
            headers = {"Authorization": f"Bearer {token}"}
            elapsed = 0
            interval = 8

            while elapsed < max_wait:
                await asyncio.sleep(interval)
                elapsed += interval

                r = await client.get(f"{self.API}/messages", headers=headers)
                if r.status_code != 200:
                    continue

                messages = r.json().get("hydra:member", [])
                for msg in messages:
                    subject = msg.get("subject", "")
                    # Instagram envoie un mail avec un code a 6 chiffres
                    # Lire le contenu complet du message
                    msg_id = msg.get("id")
                    if msg_id:
                        r2 = await client.get(f"{self.API}/messages/{msg_id}", headers=headers)
                        if r2.status_code == 200:
                            body = r2.json().get("text", "") or r2.json().get("html", [""])[0] if isinstance(r2.json().get("html"), list) else ""
                            full_text = subject + " " + str(body)
                            # Chercher un code a 6 chiffres
                            codes = re.findall(r"\b(\d{6})\b", full_text)
                            if codes:
                                return codes[0]

                print(f"   [Email] Attente... ({elapsed}s)", flush=True)

        return None


class AccountCreator:
    """Cree des comptes Instagram via Playwright + GrizzlySMS/Email + CapSolver."""

    async def create_account(self, niche: Niche, proxy: Proxy, method: str = "sms") -> IgAccount | None:
        """Cree un compte. method='sms' ou 'email'. Retourne le compte cree ou None."""
        # Verifier capacite proxy
        if not await self._check_proxy_capacity(proxy):
            await _log(niche.tenant_id, "WARNING", f"Proxy {proxy.host}:{proxy.port} sature ({proxy.accounts_count}/{proxy.max_accounts})")
            return None

        try:
            # Generer identite
            identity = await self._generate_identity(niche)

            # Generer bio IA
            bio = await self._generate_bio(niche)

            if method == "email":
                # Mode email — pas de SMS
                account = await self._create_via_email(identity, proxy, niche, bio)
                phone = ""
            else:
                # Mode SMS classique
                activation_id, phone = await self._get_sms_number()
                account = await self._create_via_playwright(
                    identity, phone, proxy, niche, bio, activation_id=activation_id,
                )

            if not account:
                return None

            # Sauvegarder en DB
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

    async def _get_sms_number(self, country: int | None = None) -> tuple[str, str]:
        """(activation_id, phone_number) depuis GrizzlySMS via getNumberV2.

        Si country=None, essaie les pays dans SMS_COUNTRY_FALLBACKS.
        """
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")
        service = os.getenv("SMS_ACTIVATE_SERVICE", "ig")
        api_url = os.getenv("SMS_API_URL", GRIZZLY_API)

        countries_to_try = [country] if country else SMS_COUNTRY_FALLBACKS

        async with httpx.AsyncClient() as client:
            for c in countries_to_try:
                resp = await client.get(
                    api_url,
                    params={
                        "api_key": sms_key,
                        "action": "getNumberV2",
                        "service": service,
                        "country": str(c),
                    },
                    timeout=30,
                )

                text = resp.text
                if text.startswith("{"):
                    data = resp.json()
                    activation_id = str(data.get("activationId", ""))
                    phone = str(data.get("phoneNumber", ""))
                    if activation_id and phone:
                        return activation_id, phone

                # Fallback ancien format ACCESS_NUMBER:ID:PHONE
                if "ACCESS_NUMBER" in text:
                    parts = text.split(":")
                    return parts[1], parts[2]

            raise ValueError(f"GrizzlySMS: aucun numero disponible (pays essayes: {countries_to_try})")

    async def _set_sms_status(self, activation_id: str, status: int) -> str:
        """Envoie setStatus a GrizzlySMS. status=1: ready, 6: done, 8: cancel."""
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")
        api_url = os.getenv("SMS_API_URL", GRIZZLY_API)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                api_url,
                params={
                    "api_key": sms_key,
                    "action": "setStatus",
                    "id": activation_id,
                    "status": str(status),
                },
                timeout=15,
            )
            return resp.text

    async def _wait_for_sms_code(self, activation_id: str) -> str | None:
        """Marque ready (status=1) puis poll GrizzlySMS toutes les 10s, max 5 min."""
        sms_key = os.getenv("SMS_ACTIVATE_KEY", "")
        api_url = os.getenv("SMS_API_URL", GRIZZLY_API)

        # Signaler qu'on est pret a recevoir le SMS
        ready_resp = await self._set_sms_status(activation_id, 1)
        print(f"   [SMS] setStatus=1 → {ready_resp}")

        for attempt in range(30):  # 30 * 10s = 5 min max
            await asyncio.sleep(10)

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    api_url,
                    params={
                        "api_key": sms_key,
                        "action": "getStatus",
                        "id": activation_id,
                    },
                    timeout=15,
                )
                text = resp.text
                if "STATUS_OK" in text:
                    code = text.split(":")[1]
                    # Confirmer la reception
                    await self._set_sms_status(activation_id, 6)
                    return code
                if "STATUS_CANCEL" in text:
                    return None
                if attempt % 3 == 0:
                    print(f"   [SMS] Attente... ({(attempt + 1) * 10}s)")

        # Timeout — annuler l'activation
        await self._set_sms_status(activation_id, 8)
        return None

    async def _solve_captcha(self, site_key: str, page_url: str) -> str | None:
        """Resout un captcha via CapSolver. Retourne le token ou None."""
        capsolver_key = os.getenv("CAPSOLVER_KEY", "")
        if not capsolver_key:
            return None

        async with httpx.AsyncClient() as client:
            # Creer la tache
            resp = await client.post(
                f"{CAPSOLVER_API}/createTask",
                json={
                    "clientKey": capsolver_key,
                    "task": {
                        "type": "ReCaptchaV2TaskProxyLess",
                        "websiteURL": page_url,
                        "websiteKey": site_key,
                    },
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("errorId", 1) != 0:
                return None

            task_id = data["taskId"]

            # Poll le resultat (max 2 min)
            for _ in range(24):
                await asyncio.sleep(5)
                result_resp = await client.post(
                    f"{CAPSOLVER_API}/getTaskResult",
                    json={"clientKey": capsolver_key, "taskId": task_id},
                    timeout=10,
                )
                result = result_resp.json()
                status = result.get("status")
                if status == "ready":
                    return result.get("solution", {}).get("gRecaptchaResponse")
                if status == "failed":
                    return None

        return None

    async def _generate_identity(self, niche: Niche) -> dict:
        """Genere une identite fictive coherente avec la niche."""
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        suffix = "".join(random.choices(string.digits, k=random.randint(2, 4)))
        # Retirer les accents pour le username (IG n'accepte que a-z 0-9 . _)
        import unicodedata
        first_clean = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode()
        last_clean = unicodedata.normalize("NFKD", last).encode("ascii", "ignore").decode()
        username = f"{first_clean.lower()}.{last_clean.lower()}{suffix}"
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

    async def _click_next(self, page, step_name: str, wait_nav: bool = True) -> bool:
        """Clique le bouton Suivant/Next et attend la transition de page."""
        # D'abord essayer get_by_role (matche button + div[role=button])
        for btn_name in ["Suivant", "Next", "S'inscrire", "Sign up", "Confirmer"]:
            try:
                btn = page.get_by_role("button", name=btn_name)
                if await btn.is_visible(timeout=1500):
                    old_url = page.url
                    await btn.click()
                    print(f"   [Playwright] {step_name} → clic: {btn_name}")
                    if wait_nav:
                        for _ in range(20):
                            await asyncio.sleep(1)
                            if page.url != old_url:
                                print(f"   [Playwright] {step_name} → page changee: {page.url}")
                                break
                        else:
                            await asyncio.sleep(2)
                    return True
            except Exception:
                continue

        # Fallback JS — chercher le bouton dans le DOM React
        clicked = await page.evaluate('''() => {
            const btns = document.querySelectorAll("button, div[role='button']");
            const names = ["Suivant", "Next", "S'inscrire", "Sign up", "Confirmer"];
            for (const btn of btns) {
                const txt = btn.textContent.trim();
                if (names.some(n => txt === n || txt.includes(n))) {
                    btn.click();
                    return txt;
                }
            }
            // Derniere tentative : submit button
            const submit = document.querySelector("button[type='submit']");
            if (submit) { submit.click(); return "submit"; }
            return null;
        }''')
        if clicked:
            print(f"   [Playwright] {step_name} → JS clic: {clicked}")
            if wait_nav:
                old_url = page.url
                for _ in range(15):
                    await asyncio.sleep(1)
                    if page.url != old_url:
                        print(f"   [Playwright] {step_name} → page changee: {page.url}")
                        break
                else:
                    await asyncio.sleep(2)
            return True

        print(f"   [Playwright] {step_name} → ERREUR: bouton introuvable")
        await page.screenshot(path=f"debug_{step_name.replace('/', '_')}_no_btn.png")
        return False

    async def _create_via_email(
        self, identity: dict, proxy: Proxy, niche: Niche, bio: str,
    ) -> bool:
        """Cree un compte Instagram via email (bypass SMS).

        Flow:
        1. Creer email temp via mail.tm
        2. Cliquer onglet 'ADRESSE E-MAIL' sur Instagram
        3. Remplir email → Suivant
        4. Attendre code verif dans inbox mail.tm
        5. Entrer code → Suivant
        6. Nom complet + mot de passe → Suivant
        7. Date de naissance → Suivant
        8. Username → Suivant
        """
        try:
            from playwright.async_api import async_playwright

            mail_client = _TempMailClient()

            # 1. Creer email temporaire
            email_addr, email_pwd, mail_token = await mail_client.create_email()
            identity["email"] = email_addr
            print(f"   [Email] Adresse: {email_addr}", flush=True)

            proxy_config = {"server": f"http://{proxy.host}:{proxy.port}"}
            if proxy.username and proxy.password:
                proxy_config["username"] = proxy.username
                proxy_config["password"] = proxy.password

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, proxy=proxy_config)
                context = await browser.new_context(
                    viewport={"width": 412, "height": 915},
                    user_agent=random.choice(USER_AGENTS),
                    locale="fr-FR",
                    timezone_id="Europe/Paris",
                )
                page = await context.new_page()
                step = 0

                # ========== PAGE 1 : Email ==========
                step += 1
                print(f"   [{step}/6] Navigation vers inscription...", flush=True)
                await page.goto(
                    "https://www.instagram.com/accounts/emailsignup/",
                    wait_until="domcontentloaded", timeout=30000,
                )
                await asyncio.sleep(5)

                # Cookie consent
                await page.evaluate('''() => {
                    const btns = document.querySelectorAll("button");
                    for (const btn of btns) {
                        const txt = btn.textContent.trim();
                        if (txt === "Autoriser tous les cookies"
                            || txt === "Allow all cookies"
                            || txt === "Tout autoriser") {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                await asyncio.sleep(random.uniform(2, 3))

                # Cliquer l'onglet "ADRESSE E-MAIL" (role="switch")
                tab_clicked = await page.evaluate('''() => {
                    const all = document.querySelectorAll("span, a, button, div[role='tab'], [role='switch'], [role='button']");
                    for (const el of all) {
                        const txt = el.textContent.trim();
                        if (txt.toLowerCase().includes("e-mail") || txt.toLowerCase().includes("email")) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                if tab_clicked:
                    print(f"   [{step}/6] Onglet email selectionne", flush=True)
                    await asyncio.sleep(1.5)
                else:
                    print(f"   [{step}/6] WARN: Onglet email non trouve", flush=True)

                # Chercher le champ email
                email_input = None
                for sel in [
                    "input[name='emailOrPhone']",
                    "input[name='email']",
                    "input[type='email']",
                    "input[aria-label*='mail']",
                    "input[aria-label*='Mail']",
                    "input[placeholder*='mail']",
                ]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=2000):
                            email_input = loc
                            break
                    except Exception:
                        continue

                if not email_input:
                    # Fallback: premier input text visible
                    all_inputs = page.locator("input[type='text'], input[type='email'], input:not([type='hidden']):not([type='tel'])")
                    count = await all_inputs.count()
                    for i in range(count):
                        inp = all_inputs.nth(i)
                        if await inp.is_visible(timeout=1000):
                            email_input = inp
                            break

                if not email_input:
                    await page.screenshot(path="debug_email_01_no_input.png")
                    print(f"   [{step}/6] ERREUR: Champ email non trouve", flush=True)
                    await browser.close()
                    return False

                await self._human_type(email_input, email_addr)
                print(f"   [{step}/6] Email saisi: {email_addr}", flush=True)
                await asyncio.sleep(random.uniform(0.8, 1.5))

                if not await self._click_next(page, f"{step}/6 Email"):
                    await page.screenshot(path="debug_email_02_no_next.png")
                    await browser.close()
                    return False

                # ========== PAGE 2 : Code email ==========
                step += 1
                print(f"   [{step}/6] Attente code email...", flush=True)
                await asyncio.sleep(3)

                # Chercher le champ code
                code_input = None
                for sel in [
                    "input[name='confirmationCode']",
                    "input[name='code']",
                    "input[name='email_confirmation_code']",
                    "input[aria-label*='confirmation']",
                    "input[aria-label*='code']",
                    "input[aria-label*='Code']",
                    "input[placeholder*='confirmation']",
                    "input[placeholder*='Code']",
                ]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=2000):
                            code_input = loc
                            break
                    except Exception:
                        continue

                if not code_input:
                    await page.screenshot(path="debug_email_03_no_code.png")
                    print(f"   [{step}/6] ERREUR: Champ code non trouve", flush=True)
                    await browser.close()
                    return False

                # Attendre le code dans l'inbox mail.tm
                code = await mail_client.wait_for_code(mail_token, max_wait=180)
                if not code:
                    print(f"   [{step}/6] ERREUR: Code email non recu", flush=True)
                    await browser.close()
                    return False

                print(f"   [{step}/6] Code recu: {code}", flush=True)
                await self._human_type(code_input, code)
                await asyncio.sleep(1)

                if not await self._click_next(page, f"{step}/6 Code"):
                    await page.screenshot(path="debug_email_04_no_next.png")
                    await browser.close()
                    return False

                # ========== PAGE 3 : Nom + Mot de passe ==========
                step += 1
                print(f"   [{step}/6] Page nom et mot de passe...", flush=True)
                await asyncio.sleep(3)

                # Nom complet
                name_input = None
                for sel in [
                    "input[name='fullName']",
                    "input[name='full_name']",
                    "input[aria-label*='complet']",
                    "input[aria-label*='Nom complet']",
                    "input[aria-label*='Full name']",
                ]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=2000):
                            name_input = loc
                            break
                    except Exception:
                        continue

                full_name = f"{identity['first_name']} {identity['last_name']}"
                if name_input:
                    await self._human_type(name_input, full_name)
                    print(f"   [{step}/6] Nom: {full_name}", flush=True)

                # Mot de passe
                pwd_input = None
                for sel in ["input[name='password']", "input[type='password']"]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=2000):
                            pwd_input = loc
                            break
                    except Exception:
                        continue
                if pwd_input:
                    await self._human_type(pwd_input, identity["password"])
                    print(f"   [{step}/6] Mot de passe saisi", flush=True)
                await asyncio.sleep(random.uniform(0.5, 1))

                if not await self._click_next(page, f"{step}/6 Name"):
                    await page.screenshot(path="debug_email_05_no_next.png")
                    await browser.close()
                    return False

                # ========== PAGE 4 : Date de naissance ==========
                step += 1
                print(f"   [{step}/6] Page date de naissance...", flush=True)
                await asyncio.sleep(3)

                # Mois FR
                months_fr = [
                    "", "janvier", "février", "mars", "avril", "mai", "juin",
                    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
                ]
                month_name = months_fr[identity["birth_month"]]

                # Selectors pour les 3 dropdowns
                selects = page.locator("select")
                sel_count = await selects.count()
                if sel_count >= 3:
                    # Mois (premier select)
                    await selects.nth(0).select_option(label=month_name)
                    await asyncio.sleep(0.3)
                    # Jour
                    await selects.nth(1).select_option(value=str(identity["birth_day"]))
                    await asyncio.sleep(0.3)
                    # Annee
                    await selects.nth(2).select_option(value=str(identity["birth_year"]))
                    await asyncio.sleep(0.3)
                    print(f"   [{step}/6] Date: {identity['birth_day']}/{identity['birth_month']}/{identity['birth_year']}", flush=True)

                if not await self._click_next(page, f"{step}/6 Birthday"):
                    await page.screenshot(path="debug_email_06_no_next.png")
                    await browser.close()
                    return False

                # ========== PAGE 5 : Username ==========
                step += 1
                print(f"   [{step}/6] Page username...", flush=True)
                await asyncio.sleep(3)

                username_input = None
                for sel in [
                    "input[name='username']",
                    "input[aria-label*='profil']",
                    "input[aria-label*='Username']",
                ]:
                    try:
                        loc = page.locator(sel).first
                        if await loc.is_visible(timeout=2000):
                            username_input = loc
                            break
                    except Exception:
                        continue

                if username_input:
                    await username_input.click(click_count=3)
                    await asyncio.sleep(0.3)
                    await self._human_type(username_input, identity["username"])
                    print(f"   [{step}/6] Username: @{identity['username']}", flush=True)
                await asyncio.sleep(random.uniform(0.5, 1))

                if not await self._click_next(page, f"{step}/6 Username"):
                    await page.screenshot(path="debug_email_07_no_next.png")
                    await browser.close()
                    return False

                # ========== PAGE 6 : Resultat ==========
                step += 1
                await asyncio.sleep(3)
                final_url = page.url
                print(f"   [{step}/6] URL finale: {final_url}", flush=True)

                success = (
                    "registered" in final_url
                    or "/accounts/login" in final_url
                    or "instagram.com" in final_url and "/accounts/emailsignup" not in final_url
                )

                if success:
                    print(f"   [{step}/6] SUCCES !", flush=True)
                else:
                    await page.screenshot(path="debug_email_08_fail.png")
                    print(f"   [{step}/6] ECHEC (url={final_url})", flush=True)

                await browser.close()
                return success

        except Exception as e:
            print(f"   [Email] ERREUR: {e}", flush=True)
            return False

    async def _create_via_playwright(
        self, identity: dict, phone: str, proxy: Proxy, niche: Niche, bio: str,
        activation_id: str | None = None,
    ) -> bool:
        """Cree le compte Instagram via Playwright. Flow multi-etapes.

        Instagram signup flow 2025+ (FR):
        1. /accounts/signup/phone/   → Telephone → Suivant
        2. Code confirmation SMS     → Suivant
        3. /accounts/signup/name/    → Nom complet + Mot de passe → Suivant
        4. /accounts/signup/username/→ Username (suggestion) → Suivant
        5. /accounts/signup/birthday/→ Date de naissance → Suivant
        6. Compte cree → redirect
        """
        try:
            from playwright.async_api import async_playwright

            proxy_config = {
                "server": f"http://{proxy.host}:{proxy.port}",
            }
            if proxy.username and proxy.password:
                proxy_config["username"] = proxy.username
                proxy_config["password"] = proxy.password

            # Detecter pays du numero et extraire le numero local
            country_search, phone_prefix, local_phone = _detect_phone_country(phone)
            is_french = phone_prefix == "33"

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
                step = 0

                # ========== PAGE 1 : Telephone ==========
                step += 1
                print(f"   [{step}/6] Navigation vers inscription...")
                await page.goto("https://www.instagram.com/accounts/emailsignup/", wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(5)

                # Cookie consent via JS (plus fiable que locators)
                clicked = await page.evaluate('''() => {
                    const btns = document.querySelectorAll("button");
                    for (const btn of btns) {
                        const txt = btn.textContent.trim();
                        if (txt === "Autoriser tous les cookies"
                            || txt === "Allow all cookies"
                            || txt === "Tout autoriser") {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                if clicked:
                    print(f"   [{step}/6] Cookies acceptes")
                    await asyncio.sleep(random.uniform(2, 3))

                # Saisie telephone
                try:
                    await page.wait_for_selector("input[type='tel']", timeout=10000)
                except Exception:
                    await page.screenshot(path="debug_01_no_phone.png")
                    print(f"   [{step}/6] ERREUR: Champ telephone non trouve")
                    await browser.close()
                    return False

                # Si numero non-francais, changer le pays dans le picker
                if not is_french:
                    print(f"   [{step}/6] Pays detecte: {country_search} (+{phone_prefix})")
                    # Cliquer sur le bouton "FR +33" pour ouvrir le picker
                    picker_opened = await page.evaluate('''() => {
                        const all = document.querySelectorAll("button, div[role='button']");
                        for (const el of all) {
                            const txt = el.textContent.trim();
                            if (txt.includes("+33") || txt.includes("+") && txt.includes("FR")) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }''')

                    if picker_opened:
                        await asyncio.sleep(1.5)
                        # Chercher le pays dans le champ de recherche
                        search_input = page.locator("input[name='filter'], input[type='search']").first
                        try:
                            await search_input.wait_for(state="visible", timeout=3000)
                            # Chercher par code pays (+234, +62, etc.)
                            await search_input.fill(f"+{phone_prefix}")
                            await asyncio.sleep(1)

                            # Cliquer sur le premier resultat (le pays correspondant)
                            selected = await page.evaluate('''() => {
                                // Chercher un element contenant le code pays dans le dialog
                                const dialog = document.querySelector("[role='dialog']");
                                if (!dialog) return null;
                                const items = dialog.querySelectorAll("div, li, button, span");
                                for (const item of items) {
                                    if (item.children.length <= 2
                                        && item.textContent.includes("+")
                                        && item.offsetParent !== null
                                        && item.offsetHeight > 20) {
                                        // Skip le header et le champ de recherche
                                        const txt = item.textContent.trim();
                                        if (txt.includes("Sélectionner") || txt.includes("Fermer")) continue;
                                        if (item.querySelector("input")) continue;
                                        item.click();
                                        return txt;
                                    }
                                }
                                return null;
                            }''')

                            if selected:
                                print(f"   [{step}/6] Pays selectionne: {selected}")
                                await asyncio.sleep(1)
                            else:
                                print(f"   [{step}/6] WARN: Pays non trouve, fermeture picker")
                                # Fermer le dialog
                                await page.evaluate('''() => {
                                    const close = document.querySelector("[role='dialog'] button");
                                    if (close) close.click();
                                }''')
                                await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"   [{step}/6] WARN: Country picker error: {e}")
                    else:
                        print(f"   [{step}/6] WARN: Bouton pays non trouve")

                phone_input = page.locator("input[type='tel']").first
                await self._human_type(phone_input, local_phone)
                print(f"   [{step}/6] Telephone saisi: {local_phone}")
                await asyncio.sleep(random.uniform(0.8, 1.5))

                if not await self._click_next(page, f"{step}/6 Phone"):
                    await page.screenshot(path="debug_02_no_next.png")
                    await browser.close()
                    return False

                await page.screenshot(path="debug_03_after_phone.png")

                # ========== PAGE 2 : Code SMS ==========
                step += 1
                print(f"   [{step}/6] Attente page code SMS...")
                if activation_id:
                    try:
                        # Chercher le champ de code — multiples selecteurs incluant placeholder FR
                        code_input = None
                        code_selectors = [
                            "input[name='confirmationCode']",
                            "input[name='code']",
                            "input[aria-label*='confirmation']",
                            "input[aria-label*='code']",
                            "input[aria-label*='Code']",
                            "input[placeholder*='confirmation']",
                            "input[placeholder*='Code']",
                            "input[placeholder*='code']",
                        ]
                        for sel in code_selectors:
                            try:
                                loc = page.locator(sel).first
                                if await loc.is_visible(timeout=2000):
                                    code_input = loc
                                    print(f"   [{step}/6] Champ code trouve via: {sel}")
                                    break
                            except Exception:
                                continue

                        # Fallback : chercher tout input visible sur la page (hors tel)
                        if not code_input:
                            try:
                                all_inputs = page.locator("input:not([type='tel']):not([type='hidden'])")
                                count = await all_inputs.count()
                                for i in range(count):
                                    inp = all_inputs.nth(i)
                                    if await inp.is_visible(timeout=1000):
                                        code_input = inp
                                        print(f"   [{step}/6] Champ code trouve via fallback (input #{i})")
                                        break
                            except Exception:
                                pass

                        if code_input:
                            await page.screenshot(path="debug_04_sms_page.png")

                            print(f"   [{step}/6] Attente SMS (max 5 min)...")
                            code = await self._wait_for_sms_code(activation_id)
                            if not code:
                                print(f"   [{step}/6] ERREUR: Code SMS non recu")
                                await page.screenshot(path="debug_05_sms_timeout.png")
                                await browser.close()
                                return False

                            await self._human_type(code_input, code)
                            print(f"   [{step}/6] Code saisi: {code}")
                            await asyncio.sleep(random.uniform(1, 2))

                            if not await self._click_next(page, f"{step}/6 SMS"):
                                await page.screenshot(path="debug_05_no_confirm.png")

                            await page.screenshot(path="debug_06_after_sms.png")
                        else:
                            print(f"   [{step}/6] Pas de champ code visible")
                            await page.screenshot(path="debug_04_no_code_field.png")
                    except Exception as e:
                        print(f"   [{step}/6] Erreur SMS: {e}")

                # ========== PAGE 3 : Nom + Mot de passe ==========
                step += 1
                print(f"   [{step}/6] Page nom et mot de passe...")

                full_name = f"{identity['first_name']} {identity['last_name']}"
                for name_sel in [
                    "input[name='fullName']",
                    "input[aria-label*='Nom complet']",
                    "input[aria-label*='nom complet']",
                    "input[placeholder*='Nom complet']",
                    "input[aria-label*='Full name']",
                ]:
                    try:
                        name_input = page.locator(name_sel).first
                        if await name_input.is_visible(timeout=5000):
                            await self._human_type(name_input, full_name)
                            print(f"   [{step}/6] Nom: {full_name}")
                            break
                    except Exception:
                        continue
                await asyncio.sleep(random.uniform(0.5, 1.2))

                for pwd_sel in [
                    "input[name='password']",
                    "input[type='password']",
                    "input[aria-label*='Mot de passe']",
                    "input[placeholder*='Mot de passe']",
                ]:
                    try:
                        pwd_input = page.locator(pwd_sel).first
                        if await pwd_input.is_visible(timeout=3000):
                            await self._human_type(pwd_input, identity["password"])
                            print(f"   [{step}/6] Mot de passe saisi")
                            break
                    except Exception:
                        continue
                await asyncio.sleep(random.uniform(1, 2))

                await page.screenshot(path="debug_07_name_filled.png")

                if not await self._click_next(page, f"{step}/6 Name"):
                    await page.screenshot(path="debug_08_no_next_name.png")

                await page.screenshot(path="debug_09_after_name.png")

                # ========== PAGE 4 : Date de naissance ==========
                # (IG affiche birthday AVANT username dans le flow actuel)
                step += 1
                print(f"   [{step}/6] Page date de naissance...")

                # Mois en francais pour les selects IG
                MOIS_FR = {
                    1: "janvier", 2: "février", 3: "mars", 4: "avril",
                    5: "mai", 6: "juin", 7: "juillet", 8: "août",
                    9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
                }

                try:
                    month_loc = page.locator("select").nth(0)
                    if await month_loc.is_visible(timeout=5000):
                        # Essayer par label FR, puis par index
                        month_val = MOIS_FR.get(identity["birth_month"], "")
                        try:
                            await month_loc.select_option(label=month_val)
                        except Exception:
                            await month_loc.select_option(index=identity["birth_month"])
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        print(f"   [{step}/6] Mois: {month_val}")

                        day_loc = page.locator("select").nth(1)
                        await day_loc.select_option(str(identity["birth_day"]))
                        await asyncio.sleep(random.uniform(0.3, 0.8))

                        year_loc = page.locator("select").nth(2)
                        await year_loc.select_option(str(identity["birth_year"]))
                        await asyncio.sleep(random.uniform(0.5, 1))

                        print(f"   [{step}/6] Date: {identity['birth_day']}/{identity['birth_month']}/{identity['birth_year']}")
                        await page.screenshot(path="debug_10_birthday_filled.png")

                        if not await self._click_next(page, f"{step}/6 Birthday"):
                            await page.screenshot(path="debug_11_no_next_bday.png")

                        await page.screenshot(path="debug_12_after_birthday.png")
                except Exception as e:
                    print(f"   [{step}/6] Pas de page birthday ou erreur: {e}")

                # ========== PAGE 5 : Username ("Nom de profil") ==========
                step += 1
                print(f"   [{step}/6] Page username (nom de profil)...")

                username_filled = False
                for user_sel in [
                    "input[name='username']",
                    "input[aria-label*='Nom de profil']",
                    "input[aria-label*='nom de profil']",
                    "input[placeholder*='Nom de profil']",
                    "input[aria-label*='utilisateur']",
                    "input[aria-label*=\"Nom d'utilisateur\"]",
                    "input[aria-label*='Username']",
                ]:
                    try:
                        user_input = page.locator(user_sel).first
                        if await user_input.is_visible(timeout=5000):
                            # Effacer la suggestion d'IG puis saisir le notre
                            await user_input.click()
                            await page.keyboard.press("Meta+a")  # Cmd+A sur macOS
                            await asyncio.sleep(0.2)
                            await page.keyboard.press("Backspace")
                            await asyncio.sleep(0.3)
                            await user_input.type(identity["username"], delay=random.uniform(50, 120))
                            username_filled = True
                            print(f"   [{step}/6] Username: @{identity['username']}")
                            break
                    except Exception:
                        continue

                if not username_filled:
                    # Fallback : chercher tout input texte visible
                    try:
                        all_inputs = page.locator("input[type='text'], input:not([type])")
                        count = await all_inputs.count()
                        for i in range(count):
                            inp = all_inputs.nth(i)
                            if await inp.is_visible(timeout=1000):
                                await inp.click()
                                await page.keyboard.press("Meta+a")
                                await asyncio.sleep(0.2)
                                await page.keyboard.press("Backspace")
                                await asyncio.sleep(0.3)
                                await inp.type(identity["username"], delay=random.uniform(50, 120))
                                username_filled = True
                                print(f"   [{step}/6] Username (fallback input #{i}): @{identity['username']}")
                                break
                    except Exception:
                        pass

                await asyncio.sleep(random.uniform(1, 2))
                await page.screenshot(path="debug_13_username_filled.png")

                if not await self._click_next(page, f"{step}/6 Username"):
                    await page.screenshot(path="debug_14_no_next_user.png")

                await page.screenshot(path="debug_14_after_username.png")

                # ========== PAGE 6 : Resultat ==========
                step += 1
                await page.screenshot(path="debug_15_final.png")
                final_url = page.url
                print(f"   [{step}/6] URL finale: {final_url}")

                success = "signup" not in final_url and "emailsignup" not in final_url
                print(f"   [{step}/6] {'SUCCES !' if success else 'A verifier (voir debug_15_final.png)'}")

                await browser.close()
                return True

        except Exception as e:
            await _log(niche.tenant_id, "ERROR", f"Playwright creation echouee: {e}", {"error": str(e)})
            return False

    async def _human_type(self, locator, text: str):
        """Simule une frappe humaine caractere par caractere."""
        await locator.click()
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await locator.type(text, delay=random.uniform(50, 120))


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
