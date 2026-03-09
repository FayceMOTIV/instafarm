"""Creation automatisee de comptes TikTok.

Stack : mail.tm (email signup prioritaire) + SMS-Man/GrizzlySMS (fallback)
        + CapSolver (CAPTCHA) + playwright-stealth enhanced.
"""

import asyncio
import json
import os
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

try:
    import nodriver as uc

    HAS_NODRIVER = True
except ImportError:
    HAS_NODRIVER = False

SMS_API_KEY = os.getenv("SMS_ACTIVATE_KEY", "")
SMS_API_URL = os.getenv("SMS_API_URL", "https://api.grizzlysms.com/stubs/handler_api.php")
CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY", "")
FIVESIM_API_KEY = os.getenv("FIVESIM_API_KEY", "")
SMSMAN_API_KEY = os.getenv("SMSMAN_API_KEY", "")

NICHE_USERNAMES = {
    "restauration": ["LePatronDuResto", "ChefConseilFr", "RestoSuccesFr", "AstucesRestau", "GestionResto"],
    "coiffure": ["SalonProConseil", "CoiffeurAstuce", "TendanceCoifFr", "AgendaSalon", "CoiffeurSucces"],
    "btp_artisan": ["ArtisanSuccesFr", "ChantierPro", "DevisArtisan", "BTPConseilFr", "MaisonRenovPro"],
    "dentiste": ["CabinetSuccesFr", "DentisteConseil", "PatientFidele", "CliniquePro", "SanteDentFr"],
    "auto_garage": ["GaragisteAstuce", "AutoProConseil", "GarageSuccesFr", "MecaProFr", "EntretienAuto"],
    "sport_fitness": ["CoachProFr", "FitnessSucees", "SportPro2024", "CoachingFr", "GymSuccesFr"],
    "immobilier": ["ImmoProFr", "AgentSucces", "ImmoConseilFr", "MandataireTop", "ImmoAstuceFr"],
    "photographe": ["PhotoProFr", "StudioSucces", "PhotographeTop", "PhotoConseil", "ArtPhotoFr"],
}

PLAYWRIGHT_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-infobars",
    "--window-size=390,844",
    "--lang=fr-FR",
]

# Use real Chrome instead of Chromium when available (much harder to detect)
USE_REAL_CHROME = True


# ──────────────────────────────────────────────────────────
# mail.tm Client (temp email for signup — avoids SMS entirely)
# ──────────────────────────────────────────────────────────

class MailTMClient:
    """Client API mail.tm pour email temporaire."""

    BASE_URL = "https://api.mail.tm"

    async def create_email(self) -> dict | None:
        """Cree une adresse email temporaire. Retourne {email, password, token}."""
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Get available domain
            r = await client.get(f"{self.BASE_URL}/domains")
            if r.status_code != 200:
                print(f"[MAILTM] Domains error: {r.status_code}")
                return None

            domains = r.json().get("hydra:member", [])
            if not domains:
                print("[MAILTM] No domains available")
                return None

            domain = domains[0]["domain"]
            # Random username: 8-12 chars lowercase + digits
            user = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(8, 12)))
            email = f"{user}@{domain}"
            pwd = "".join(random.choices(string.ascii_letters + string.digits, k=16))

            # 2. Create account
            r = await client.post(
                f"{self.BASE_URL}/accounts",
                json={"address": email, "password": pwd},
            )
            if r.status_code not in (200, 201):
                print(f"[MAILTM] Account create error: {r.status_code} {r.text[:200]}")
                return None

            # 3. Get auth token
            r = await client.post(
                f"{self.BASE_URL}/token",
                json={"address": email, "password": pwd},
            )
            if r.status_code != 200:
                print(f"[MAILTM] Token error: {r.status_code}")
                return None

            token = r.json().get("token", "")
            print(f"[MAILTM] Email cree: {email}")
            return {"email": email, "password": pwd, "token": token}

    async def wait_for_code(self, token: str, max_wait: int = 120) -> str | None:
        """Attend le code de verification TikTok. Retourne le code 6 digits ou None."""
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            for attempt in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(f"{self.BASE_URL}/messages", headers=headers)
                if r.status_code != 200:
                    print(f"  [MAILTM] Messages error: {r.status_code}")
                    continue

                messages = r.json().get("hydra:member", [])
                for msg in messages:
                    subject = (msg.get("subject") or "").lower()
                    # TikTok verification emails have subjects like "verification code" or "[TikTok]"
                    if "tiktok" in subject or "verif" in subject or "code" in subject:
                        # Get full message
                        msg_id = msg["id"]
                        r2 = await client.get(f"{self.BASE_URL}/messages/{msg_id}", headers=headers)
                        if r2.status_code == 200:
                            body = r2.json().get("text", "") or r2.json().get("html", [""])[0]
                            # Extract 6-digit code
                            code = re.search(r"\b(\d{6})\b", body)
                            if code:
                                return code.group(1)
                            # Try 4-digit
                            code = re.search(r"\b(\d{4})\b", body)
                            if code:
                                return code.group(1)
                            print(f"  [MAILTM] Email found but no code in: {body[:200]}")
                            return None

                print(f"  [MAILTM] wait... ({attempt * 5}s/{max_wait}s) {len(messages)} msgs")

        return None


# ──────────────────────────────────────────────────────────
# Enhanced Stealth (anti-detection TikTok)
# ──────────────────────────────────────────────────────────

STEALTH_JS = """
() => {
    // Override navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

    // Chrome runtime
    window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };

    // Permissions API
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            origQuery(params)
    );

    // Plugins (simulate real browser)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['fr-FR', 'fr', 'en-US', 'en'],
    });

    // Hardware concurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 4});

    // Device memory
    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});

    // WebGL vendor/renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Apple Inc.';
        if (param === 37446) return 'Apple GPU';
        return getParameter.call(this, param);
    };

    // Prevent iframe detection
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() { return window; }
    });

    // Connection type
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', {get: () => 50});
    }
}
"""


async def _apply_enhanced_stealth(page):
    """Applique stealth avancee en plus de playwright-stealth."""
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except ImportError:
        pass
    await page.evaluate(STEALTH_JS)


async def _human_scroll_and_move(page):
    """Simule un comportement humain : scroll + mouvements souris."""
    # Petit scroll down
    await page.mouse.move(random.randint(150, 250), random.randint(300, 500))
    await asyncio.sleep(random.uniform(0.3, 0.8))
    await page.mouse.wheel(0, random.randint(50, 150))
    await asyncio.sleep(random.uniform(0.5, 1.0))
    # Mouvement souris naturel
    for _ in range(random.randint(2, 4)):
        await page.mouse.move(
            random.randint(50, 350),
            random.randint(100, 700),
            steps=random.randint(5, 15),
        )
        await asyncio.sleep(random.uniform(0.2, 0.5))


# ──────────────────────────────────────────────────────────
# GrizzlySMS Client (API compatible SMS-activate)
# ──────────────────────────────────────────────────────────

class GrizzlySMSClient:
    """Client API GrizzlySMS (format SMS-activate)."""

    def __init__(self, api_key: str, api_url: str):
        self.api_key = api_key
        self.api_url = api_url

    async def get_balance(self) -> float:
        async with httpx.AsyncClient() as client:
            r = await client.get(self.api_url, params={
                "api_key": self.api_key,
                "action": "getBalance",
            })
            text = r.text.strip()
            if text.startswith("ACCESS_BALANCE:"):
                return float(text.split(":")[1])
            print(f"[SMS] Balance error: {text}")
            return 0

    async def buy_number(self, service: str = "lf", country: str = "78") -> dict | None:
        """Achete un numero. service='lf' = TikTok, country='78' = France (GrizzlySMS)."""
        async with httpx.AsyncClient() as client:
            r = await client.get(self.api_url, params={
                "api_key": self.api_key,
                "action": "getNumber",
                "service": service,
                "country": country,
            })
            text = r.text.strip()
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                order_id = parts[1]
                phone = parts[2]
                if not phone.startswith("+"):
                    phone = "+" + phone
                return {"order_id": order_id, "phone": phone}

            print(f"[SMS] Buy error: {text}")
            return None

    async def wait_for_sms(self, order_id: str, max_wait: int = 120) -> str | None:
        """Attend le SMS OTP. Retourne le code ou None."""
        async with httpx.AsyncClient() as client:
            # D'abord signaler qu'on attend le SMS
            await client.get(self.api_url, params={
                "api_key": self.api_key,
                "action": "setStatus",
                "id": order_id,
                "status": "1",  # SMS envoye, on attend
            })

            for attempt in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(self.api_url, params={
                    "api_key": self.api_key,
                    "action": "getStatus",
                    "id": order_id,
                })
                text = r.text.strip()

                if text.startswith("STATUS_OK:"):
                    code_text = text.split(":")[1]
                    code = re.search(r"\b(\d{4,6})\b", code_text)
                    if code:
                        return code.group(1)
                    return code_text.strip()

                if text in ("STATUS_CANCEL", "STATUS_WAIT_RETRY"):
                    print(f"[SMS] Order {order_id} status={text}")
                    return None

                print(f"  SMS wait... ({attempt * 5}s/{max_wait}s) {text}")

        return None

    async def cancel_number(self, order_id: str):
        async with httpx.AsyncClient() as client:
            await client.get(self.api_url, params={
                "api_key": self.api_key,
                "action": "setStatus",
                "id": order_id,
                "status": "8",  # Annuler
            })


# ──────────────────────────────────────────────────────────
# 5sim.net Client (fallback SMS provider)
# ──────────────────────────────────────────────────────────

class FiveSimClient:
    """Client API 5sim.net pour reception SMS."""

    BASE_URL = "https://5sim.net/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

    async def get_balance(self) -> float:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.BASE_URL}/user/profile", headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("balance", 0)
            print(f"[5SIM] Balance error: {r.status_code} {r.text[:200]}")
            return 0

    async def buy_number(self, country: str = "france", product: str = "tiktok") -> dict | None:
        """Achete un numero 5sim. country='france', product='tiktok'."""
        url = f"{self.BASE_URL}/user/buy/activation/{country}/any/{product}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=self.headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                phone = data.get("phone", "")
                if not phone.startswith("+"):
                    phone = "+" + phone
                return {"order_id": str(data["id"]), "phone": phone}
            print(f"[5SIM] Buy error: {r.status_code} {r.text[:200]}")
            return None

    async def wait_for_sms(self, order_id: str, max_wait: int = 180) -> str | None:
        """Attend le SMS OTP via 5sim. Retourne le code ou None."""
        url = f"{self.BASE_URL}/user/check/{order_id}"
        async with httpx.AsyncClient() as client:
            for attempt in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(url, headers=self.headers, timeout=10)
                if r.status_code != 200:
                    print(f"  [5SIM] Check error: {r.status_code}")
                    continue
                data = r.json()
                status = data.get("status", "")
                sms_list = data.get("sms", [])

                if sms_list:
                    code_text = sms_list[0].get("code", "")
                    if code_text:
                        return code_text
                    # Extraire code du texte brut
                    text = sms_list[0].get("text", "")
                    code = re.search(r"\b(\d{4,6})\b", text)
                    if code:
                        return code.group(1)

                if status in ("CANCELED", "TIMEOUT", "BANNED"):
                    print(f"  [5SIM] Order {order_id} status={status}")
                    return None

                print(f"  [5SIM] wait... ({attempt * 5}s/{max_wait}s) status={status}")

        return None

    async def cancel_number(self, order_id: str):
        url = f"{self.BASE_URL}/user/cancel/{order_id}"
        async with httpx.AsyncClient() as client:
            await client.get(url, headers=self.headers, timeout=10)


# ──────────────────────────────────────────────────────────
# SMS-Man Client (sms-man.com)
# ──────────────────────────────────────────────────────────

# SMS-Man country IDs (les plus courants)
SMSMAN_COUNTRIES = {"UK": 10, "Indonesia": 7, "France": 73, "Russia": 1, "India": 14}
# SMS-Man application ID pour TikTok
SMSMAN_TIKTOK_APP_ID = 56  # TikTok/Douyin


class SmsManClient:
    """Client API sms-man.com pour reception SMS."""

    BASE_URL = "https://api.sms-man.com/control"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def get_balance(self) -> float:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/get-balance",
                params={"token": self.api_key},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                return float(data.get("balance", 0))
            print(f"[SMSMAN] Balance error: {r.status_code} {r.text[:200]}")
            return 0

    async def buy_number(self, country_id: int = 10, application_id: int = 56) -> dict | None:
        """Achete un numero sms-man. country_id=10=UK, application_id=56=TikTok."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/get-number",
                params={
                    "token": self.api_key,
                    "country_id": country_id,
                    "application_id": application_id,
                },
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if "number" in data:
                    phone = data["number"]
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    return {
                        "order_id": str(data.get("request_id", "")),
                        "phone": phone,
                    }
            print(f"[SMSMAN] Buy error: {r.status_code} {r.text[:200]}")
            return None

    async def wait_for_sms(self, order_id: str, max_wait: int = 180) -> str | None:
        """Attend le SMS OTP. Retourne le code ou None."""
        async with httpx.AsyncClient() as client:
            for attempt in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(
                    f"{self.BASE_URL}/get-sms",
                    params={
                        "token": self.api_key,
                        "request_id": order_id,
                    },
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()
                    sms_code = data.get("sms_code")
                    if sms_code:
                        return str(sms_code)
                    error_code = data.get("error_code")
                    if error_code == "wait_sms":
                        print(f"  [SMSMAN] wait... ({attempt * 5}s/{max_wait}s)")
                        continue
                    if error_code in ("expired", "no_sms"):
                        print(f"  [SMSMAN] {error_code}")
                        return None
                else:
                    print(f"  [SMSMAN] check error: {r.status_code}")

        return None

    async def cancel_number(self, order_id: str):
        async with httpx.AsyncClient() as client:
            await client.get(
                f"{self.BASE_URL}/set-status",
                params={
                    "token": self.api_key,
                    "request_id": order_id,
                    "status": "reject",
                },
                timeout=10,
            )


# ──────────────────────────────────────────────────────────
# CapSolver Client
# ──────────────────────────────────────────────────────────

async def _solve_captcha_capsolver(page) -> bool:
    """Resout le CAPTCHA TikTok via CapSolver API."""
    if not CAPSOLVER_KEY:
        print("[CAPTCHA] CAPSOLVER_KEY not set, skipping")
        return False

    # Detecter si un CAPTCHA est present
    captcha_present = False
    for selector in [
        '[id*="captcha"]',
        '[class*="captcha"]',
        'iframe[src*="captcha"]',
        '[data-e2e="captcha"]',
    ]:
        try:
            el = page.locator(selector).first
            if await el.is_visible(timeout=2000):
                captcha_present = True
                break
        except Exception:
            continue

    if not captcha_present:
        print("[CAPTCHA] Pas de CAPTCHA detecte")
        return True

    print("[CAPTCHA] CAPTCHA detecte, resolution via CapSolver...")

    try:
        async with httpx.AsyncClient() as client:
            page_url = page.url

            # Creer la tache CapSolver (Turnstile)
            create_resp = await client.post(
                "https://api.capsolver.com/createTask",
                json={
                    "clientKey": CAPSOLVER_KEY,
                    "task": {
                        "type": "AntiTurnstileTaskProxyLess",
                        "websiteURL": page_url,
                        "websiteKey": "0x4AAAAAAADnPIDROrmt1Wwj",
                    },
                },
                timeout=30,
            )

            if create_resp.status_code != 200:
                print(f"[CAPTCHA] CapSolver create error: {create_resp.text[:200]}")
                return False

            result = create_resp.json()
            task_id = result.get("taskId")
            if not task_id:
                print(f"[CAPTCHA] CapSolver: {result.get('errorDescription', 'no taskId')}")
                return False

            print(f"[CAPTCHA] Task cree: {task_id}")

            # Attendre le resultat
            for _ in range(30):
                await asyncio.sleep(3)
                check_resp = await client.post(
                    "https://api.capsolver.com/getTaskResult",
                    json={"clientKey": CAPSOLVER_KEY, "taskId": task_id},
                    timeout=15,
                )
                check_result = check_resp.json()
                status = check_result.get("status")

                if status == "ready":
                    token = check_result.get("solution", {}).get("token")
                    if token:
                        # Injecter le token dans la page
                        await page.evaluate(
                            """(token) => {
                                const input = document.querySelector('[name="cf-turnstile-response"]');
                                if (input) input.value = token;
                                const cb = window.turnstileCallback || window.onTurnstileSuccess;
                                if (cb) cb(token);
                            }""",
                            token,
                        )
                        print("[CAPTCHA] Resolu via CapSolver!")
                        await asyncio.sleep(2)
                        return True

                if status == "failed":
                    print(f"[CAPTCHA] CapSolver failed: {check_result.get('errorDescription')}")
                    return False

        return False

    except Exception as e:
        print(f"[CAPTCHA] CapSolver error: {e}")
        return False


# ──────────────────────────────────────────────────────────
# Account Creation
# ──────────────────────────────────────────────────────────

# Mapping pays : GrizzlySMS code, phone prefix, locale/timezone, nom dans dropdown TikTok
COUNTRY_CONFIGS = [
    {"name": "UK", "grizzly": "16", "prefix": "+44", "locale": "en-GB", "tz": "Europe/London", "search": "United Kingdom"},
    {"name": "Indonesia", "grizzly": "6", "prefix": "+62", "locale": "id-ID", "tz": "Asia/Jakarta", "search": "Indonesia"},
    {"name": "France", "grizzly": "78", "prefix": "+33", "locale": "fr-FR", "tz": "Europe/Paris", "search": "France"},
]


async def create_tiktok_account(
    niche: str,
    proxy: str | None = None,
    save_cookies_path: str | None = None,
    headless: bool = True,
) -> dict:
    """Cree un compte TikTok — email (mail.tm) en priorite, SMS en fallback."""

    # ═══════════════════════════════════════════════════════
    # Phase 1 : EMAIL SIGNUP (mail.tm — gratuit, pas de SMS)
    # ═══════════════════════════════════════════════════════
    print(f"\n[ACCOUNT] ═══ Phase 1: EMAIL SIGNUP pour {niche} ═══")
    email_result = await _attempt_tiktok_email_signup(
        niche=niche,
        proxy=proxy,
        save_cookies_path=save_cookies_path,
        headless=headless,
    )
    if email_result["success"]:
        return email_result

    email_error = email_result.get("error", "unknown")
    print(f"[ACCOUNT] Email signup echoue: {email_error}")

    # ═══════════════════════════════════════════════════════
    # Phase 2 : SMS-Man fallback (UK, Indonesia)
    # ═══════════════════════════════════════════════════════
    if SMSMAN_API_KEY:
        smsman_url = "https://api.sms-man.com/stubs/handler_api.php"
        smsman_client = GrizzlySMSClient(SMSMAN_API_KEY, smsman_url)
        balance = await smsman_client.get_balance()
        print(f"\n[ACCOUNT] ═══ Phase 2: SMS-Man (balance: {balance} RUB) ═══")

        if balance >= 5:
            for country_cfg in COUNTRY_CONFIGS[:2]:
                cname = country_cfg["name"]
                print(f"\n[ACCOUNT] SMS-Man 'lf' {cname}...")

                result = await _attempt_tiktok_signup(
                    niche=niche,
                    sms_client=smsman_client,
                    sms_service="lf",
                    sms_country=country_cfg["grizzly"],
                    phone_prefix=country_cfg["prefix"],
                    country_search=country_cfg["search"],
                    browser_locale=country_cfg["locale"],
                    browser_tz=country_cfg["tz"],
                    proxy=proxy,
                    save_cookies_path=save_cookies_path,
                    headless=headless,
                )

                if result["success"]:
                    return result

                wait = 10 + random.randint(0, 10)
                print(f"[ACCOUNT] Attente {wait}s...")
                await asyncio.sleep(wait)

    # ═══════════════════════════════════════════════════════
    # Phase 3 : GrizzlySMS fallback
    # ═══════════════════════════════════════════════════════
    if SMS_API_KEY:
        sms_client = GrizzlySMSClient(SMS_API_KEY, SMS_API_URL)
        balance = await sms_client.get_balance()
        print(f"\n[ACCOUNT] ═══ Phase 3: GrizzlySMS (balance: {balance} RUB) ═══")

        if balance >= 5:
            for country_cfg in COUNTRY_CONFIGS[:2]:
                cname = country_cfg["name"]
                print(f"\n[ACCOUNT] GrizzlySMS 'ds' {cname}...")
                result = await _attempt_tiktok_signup(
                    niche=niche,
                    sms_client=sms_client,
                    sms_service="ds",
                    sms_country=country_cfg["grizzly"],
                    phone_prefix=country_cfg["prefix"],
                    country_search=country_cfg["search"],
                    browser_locale=country_cfg["locale"],
                    browser_tz=country_cfg["tz"],
                    proxy=proxy,
                    save_cookies_path=save_cookies_path,
                    headless=headless,
                )
                if result["success"]:
                    return result

    return {
        "success": False,
        "error": f"Toutes methodes echouees. Email: {email_error}",
    }


async def _attempt_tiktok_signup(
    niche: str,
    sms_client,
    sms_service: str = "ds",
    sms_country: str = "16",
    phone_prefix: str = "+44",
    country_search: str = "United Kingdom",
    browser_locale: str = "en-GB",
    browser_tz: str = "Europe/London",
    proxy: str | None = None,
    save_cookies_path: str | None = None,
    headless: bool = True,
) -> dict:
    """Une tentative de creation de compte TikTok avec un nouveau numero."""
    username_base = random.choice(NICHE_USERNAMES.get(niche, ["ProFrance"]))
    username = f"{username_base}{random.randint(10, 99)}"
    password = _generate_password()

    if isinstance(sms_client, SmsManClient):
        provider_name = "SMS-Man"
    elif isinstance(sms_client, FiveSimClient):
        provider_name = "5sim"
    else:
        provider_name = "GrizzlySMS"
    print(f"[ACCOUNT] Achat numero via {provider_name} (service={sms_service}, country={sms_country})...")

    if isinstance(sms_client, SmsManClient):
        number_info = await sms_client.buy_number(
            country_id=int(sms_country),
            application_id=SMSMAN_TIKTOK_APP_ID,
        )
    elif isinstance(sms_client, FiveSimClient):
        number_info = await sms_client.buy_number(country=sms_country, product=sms_service)
    else:
        number_info = await sms_client.buy_number(service=sms_service, country=sms_country)
    if not number_info:
        return {"success": False, "error": f"Echec achat numero {provider_name}"}

    phone = number_info["phone"]
    order_id = number_info["order_id"]
    print(f"  Numero: {phone} (order: {order_id})")

    if not save_cookies_path:
        cookies_dir = Path("/tmp/tiktok_cookies")
        cookies_dir.mkdir(parents=True, exist_ok=True)
        save_cookies_path = str(cookies_dir / f"{niche}_{username}.txt")

    async with async_playwright() as p:
        launch_kwargs = {"headless": headless, "args": PLAYWRIGHT_ARGS}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        browser = await p.chromium.launch(**launch_kwargs)
        print(f"  Browser: locale={browser_locale}, tz={browser_tz}")
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            locale=browser_locale,
            timezone_id=browser_tz,
        )

        page = await context.new_page()
        await _apply_enhanced_stealth(page)

        try:
            # 0. Navigation naturelle homepage d'abord
            print("[ACCOUNT] Navigation homepage...")
            await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(2, 4))
            await _human_scroll_and_move(page)

            # Accepter cookies sur la homepage
            for consent_sel in [
                'button:has-text("Accept all")',
                'button:has-text("Accepter tout")',
                'button:has-text("Accept")',
                'button:has-text("Allow all")',
                '[data-testid="cookie-banner-accept"]',
            ]:
                try:
                    btn = page.locator(consent_sel).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            # 1. Page inscription
            print("[ACCOUNT] Navigation signup...")
            await page.goto(
                "https://www.tiktok.com/signup/phone-or-email/phone",
                wait_until="networkidle",
                timeout=30000,
            )
            await asyncio.sleep(random.uniform(2, 4))
            await _human_scroll_and_move(page)
            await page.screenshot(path="/tmp/tiktok_step1_loaded.png")
            print(f"  Step 1 URL: {page.url}")

            # 2. Supprimer overlays restants
            for consent_sel in [
                'button:has-text("Accept all")',
                'button:has-text("Accepter tout")',
                'button:has-text("Accept")',
                'button:has-text("Allow")',
            ]:
                try:
                    btn = page.locator(consent_sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

            # Supprimer tous les floating-ui portals qui bloquent les clics
            await page.evaluate("""
                () => {
                    document.querySelectorAll('[data-floating-ui-portal]').forEach(el => el.remove());
                    document.querySelectorAll('[id^="floating-ui"]').forEach(el => el.remove());
                    document.querySelectorAll('.tiktok-cookie-banner').forEach(el => el.remove());
                }
            """)
            await asyncio.sleep(0.5)

            # 3. Date de naissance (selectors multiples)
            print("[ACCOUNT] Birthday...")
            birthday_done = False
            # Methode 1: data-e2e selectors
            for month_sel in ['[data-e2e="birthday-month"]', 'select[name="month"]', 'select:nth-of-type(1)']:
                try:
                    month = page.locator(month_sel).first
                    if await month.is_visible(timeout=2000):
                        await month.select_option(str(random.randint(1, 12)))
                        await asyncio.sleep(0.3)
                        for day_sel in ['[data-e2e="birthday-day"]', 'select[name="day"]', 'select:nth-of-type(2)']:
                            try:
                                day = page.locator(day_sel).first
                                if await day.is_visible(timeout=1000):
                                    await day.select_option(str(random.randint(1, 28)))
                                    break
                            except Exception:
                                continue
                        await asyncio.sleep(0.3)
                        for year_sel in ['[data-e2e="birthday-year"]', 'select[name="year"]', 'select:nth-of-type(3)']:
                            try:
                                year = page.locator(year_sel).first
                                if await year.is_visible(timeout=1000):
                                    await year.select_option(str(random.randint(1985, 1998)))
                                    break
                            except Exception:
                                continue
                        await asyncio.sleep(0.5)
                        # Cliquer Next/Continue
                        for next_sel in [
                            '[data-e2e="birthday-continue"]',
                            'button[type="submit"]',
                            'button:has-text("Next")',
                            'button:has-text("Suivant")',
                        ]:
                            try:
                                nbtn = page.locator(next_sel).first
                                if await nbtn.is_visible(timeout=2000):
                                    await nbtn.click()
                                    birthday_done = True
                                    break
                            except Exception:
                                continue
                        break
                except Exception:
                    continue

            if birthday_done:
                await asyncio.sleep(1.5)
            await page.screenshot(path="/tmp/tiktok_step3_birthday.png")

            # 4. Numero de telephone (selectors robustes)
            print(f"[ACCOUNT] Saisie numero {phone}...")
            phone_input = None
            for sel in [
                '[data-e2e="signup-phone-input"]',
                'input[name="mobile"]',
                'input[placeholder*="phone" i]',
                'input[placeholder*="numero" i]',
                'input[placeholder*="numéro" i]',
                'input[type="tel"]',
                'input[name="phoneNumber"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        phone_input = el
                        print(f"  Phone input found: {sel}")
                        break
                except Exception:
                    continue

            if not phone_input:
                # Dernier recours: chercher tout input visible
                all_inputs = page.locator('input:visible')
                count = await all_inputs.count()
                print(f"  {count} inputs visibles trouves")
                for i in range(count):
                    inp = all_inputs.nth(i)
                    placeholder = await inp.get_attribute("placeholder") or ""
                    input_type = await inp.get_attribute("type") or ""
                    name = await inp.get_attribute("name") or ""
                    print(f"    input[{i}]: type={input_type} name={name} placeholder={placeholder}")
                    if input_type == "tel" or "phone" in (placeholder + name).lower():
                        phone_input = inp
                        break

            if not phone_input:
                await page.screenshot(path=f"/tmp/tiktok_no_phone_{niche}.png")
                await browser.close()
                await sms_client.cancel_number(order_id)
                return {"success": False, "error": "Phone input introuvable. Screenshot saved."}

            # Nettoyer overlays avant de cliquer
            await _remove_overlays(page)

            # Debug : dump le HTML parent du phone input pour comprendre le selecteur pays
            parent_html = await page.evaluate("""
                () => {
                    const ph = document.querySelector('input[name="mobile"]') || document.querySelector('input[type="tel"]');
                    if (!ph) return 'NO_INPUT';
                    // Remonter 3 niveaux et capturer le HTML
                    let el = ph;
                    for (let i = 0; i < 4 && el.parentElement; i++) el = el.parentElement;
                    return el.innerHTML.slice(0, 1500);
                }
            """)
            print(f"  [DEBUG HTML] {parent_html[:500]}")

            # Selectionner le bon pays dans le dropdown TikTok
            await _select_tiktok_country(page, phone_prefix, country_search)

            # Convertir en numero local (sans prefix international)
            phone_local = phone
            if phone.startswith(phone_prefix):
                phone_local = phone[len(phone_prefix):]
                # UK: +447xxx -> 7xxx (pas de 0 devant pour TikTok)
                # ID: +628xxx -> 8xxx
                # FR: +337xxx -> 7xxx (TikTok attend sans le 0)
            phone_local = phone_local.lstrip("0")
            print(f"  Numero local: {phone_local} (prefix {phone_prefix})")

            await phone_input.click(force=True)
            await asyncio.sleep(0.5)
            await _type_like_human(phone_input, phone_local)
            await asyncio.sleep(1)
            await page.screenshot(path="/tmp/tiktok_step4_phone.png")

            # 5. CAPTCHA (CapSolver)
            print("[ACCOUNT] CAPTCHA check...")
            await _solve_captcha_capsolver(page)

            # 6. Envoyer OTP
            await _remove_overlays(page)
            send_code_btn = None
            for sel in [
                '[data-e2e="signup-send-code-btn"]',
                'button:has-text("Send code")',
                'button:has-text("Envoyer")',
                'button:has-text("Envoyer le code")',
                'a:has-text("Send code")',
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        send_code_btn = btn
                        break
                except Exception:
                    continue

            if send_code_btn:
                await send_code_btn.click(force=True)
                print("[ACCOUNT] Code SMS envoye...")
            else:
                print("[ACCOUNT] Bouton Send code introuvable, tentative Enter...")
                await page.keyboard.press("Enter")
            await asyncio.sleep(3)
            await page.screenshot(path="/tmp/tiktok_step6_sendcode.png")

            # 6b. Verifier erreurs + captcha apres envoi
            page_text = await page.evaluate("() => document.body.innerText.slice(0, 2000)")
            # Chercher messages d'erreur TikTok
            error_keywords = [
                "too many attempts", "try again later", "invalid phone",
                "not valid", "already registered", "error", "something went wrong",
                "captcha", "verify", "slide", "puzzle",
            ]
            for kw in error_keywords:
                if kw.lower() in page_text.lower():
                    print(f"  [POST-SEND] Detected: '{kw}' in page text")

            # Verifier si un captcha slider/puzzle est apparu
            captcha_after = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[id*="captcha"], [class*="captcha"], [class*="Captcha"], [class*="verify"], iframe[src*="captcha"]');
                    if (els.length > 0) {
                        return Array.from(els).map(e => ({
                            tag: e.tagName,
                            id: e.id,
                            cls: (e.className || '').toString().slice(0, 80),
                            visible: e.getBoundingClientRect().height > 0,
                        }));
                    }
                    return null;
                }
            """)
            if captcha_after:
                print(f"  [POST-SEND] CAPTCHA elements found: {captcha_after}")
            else:
                print("  [POST-SEND] No captcha, no obvious error")

            # 7. Attendre OTP (180s)
            otp_code = await sms_client.wait_for_sms(order_id, max_wait=180)
            if not otp_code:
                await browser.close()
                await sms_client.cancel_number(order_id)
                return {"success": False, "error": "Timeout SMS OTP (180s)"}

            print(f"  OTP recu: {otp_code}")

            otp_input = page.locator('[data-e2e="signup-code-input"]').first
            if not await otp_input.is_visible(timeout=3000):
                otp_input = page.locator('input[placeholder*="code" i]').first
            await otp_input.click()
            await _type_like_human(otp_input, otp_code)
            await asyncio.sleep(1)

            # 8. Mot de passe
            try:
                password_input = page.locator('[data-e2e="signup-password"]').first
                if await password_input.is_visible(timeout=3000):
                    await _type_like_human(password_input, password)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            # 9. Sign Up
            try:
                signup_btn = page.locator('[data-e2e="signup-submit-button"]').first
                if await signup_btn.is_visible(timeout=3000):
                    await signup_btn.click()
                    await asyncio.sleep(3)
            except Exception:
                pass

            # 10. Verifier succes
            await page.wait_for_timeout(3000)
            current_url = page.url
            is_logged_in = (
                "/foryou" in current_url
                or "/following" in current_url
                or "tiktok.com/home" in current_url
                or "/signup" not in current_url
            )

            if not is_logged_in:
                await page.screenshot(path=f"/tmp/tiktok_signup_failed_{niche}.png")
                await browser.close()
                return {"success": False, "error": f"Signup may have failed, url: {current_url}"}

            print(f"  Inscription reussie! URL: {current_url}")

            # 11. Sauvegarder cookies
            await _save_cookies_netscape(context, save_cookies_path)
            print(f"  Cookies: {save_cookies_path}")

            await browser.close()

            return {
                "success": True,
                "username": username,
                "phone": phone,
                "password": password,
                "cookies_path": save_cookies_path,
                "niche": niche,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            try:
                await page.screenshot(path=f"/tmp/tiktok_error_{niche}.png")
            except Exception:
                pass
            await browser.close()
            await sms_client.cancel_number(order_id)
            return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────
# Email-based TikTok Signup — nodriver (bypass CDP detection)
# ──────────────────────────────────────────────────────────

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


async def _dismiss_tiktok_popups(tab):
    """Dismiss cookie banner + GDPR popups via nodriver."""
    for text in ["Tout autoriser", "J'ai compris", "Accept all", "Allow all"]:
        try:
            btn = await tab.find(text, best_match=True)
            if btn:
                await btn.click()
                print(f"  Popup dismissed: '{text}'")
                await asyncio.sleep(1)
        except Exception:
            continue


async def _save_cookies_nodriver(tab, output_path: str):
    """Save cookies from nodriver tab in Netscape format (includes httpOnly)."""
    try:
        cookies_data = await tab.evaluate(
            """(() => {
                // document.cookie misses httpOnly — but it's what we can get from JS
                return document.cookie;
            })()"""
        )
    except Exception:
        cookies_data = ""

    # Also try CDP for full cookie list
    cdp_cookies = []
    try:
        import nodriver.cdp.network as net

        cdp_cookies = await tab.send(net.get_all_cookies())
    except Exception:
        pass

    with open(output_path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n# Generated by InstaFarm (nodriver)\n\n")

        if cdp_cookies:
            for c in cdp_cookies:
                domain = c.domain if hasattr(c, "domain") else ".tiktok.com"
                if not domain.startswith("."):
                    domain = "." + domain
                name = c.name if hasattr(c, "name") else ""
                value = c.value if hasattr(c, "value") else ""
                path = c.path if hasattr(c, "path") else "/"
                secure = "TRUE" if (hasattr(c, "secure") and c.secure) else "FALSE"
                expires = str(int(c.expires)) if (hasattr(c, "expires") and c.expires) else "0"
                sub = "TRUE" if domain.startswith(".") else "FALSE"
                f.write(f"{domain}\t{sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
        else:
            # Fallback: parse document.cookie
            for pair in (cookies_data or "").split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    f.write(f".tiktok.com\tTRUE\t/\tTRUE\t0\t{name.strip()}\t{value.strip()}\n")

    print(f"  Cookies saved: {len(cdp_cookies) or 'JS-only'} entries")


async def _attempt_tiktok_email_signup(
    niche: str,
    proxy: str | None = None,
    save_cookies_path: str | None = None,
    headless: bool = True,
) -> dict:
    """Cree un compte TikTok via email (mail.tm) + nodriver (bypass CDP detection).

    Playwright est TOUJOURS detecte par TikTok (CDP fingerprint).
    nodriver patche Chrome pour masquer les traces CDP.

    Flow TikTok email (FR) — page unique :
      1. Birthday (combobox custom React) via JS clicks
      2. Email input
      3. Password input
      4. "Envoyer le code" → mail.tm recoit le code
      5. Code input
      6. "Suivant" → compte cree
    """
    if not HAS_NODRIVER:
        return {"success": False, "error": "nodriver required. pip install nodriver"}

    username_base = random.choice(NICHE_USERNAMES.get(niche, ["ProFrance"]))
    username = f"{username_base}{random.randint(10, 99)}"
    password = _generate_password()

    # 1. Email temporaire
    mail_client = MailTMClient()
    email_info = await mail_client.create_email()
    if not email_info:
        return {"success": False, "error": "Echec creation email temporaire (mail.tm)"}

    email = email_info["email"]
    email_token = email_info["token"]
    print(f"[ACCOUNT-EMAIL] Email: {email} | Niche: {niche}")

    if not save_cookies_path:
        cookies_dir = Path("/tmp/tiktok_cookies")
        cookies_dir.mkdir(parents=True, exist_ok=True)
        save_cookies_path = str(cookies_dir / f"{niche}_{username}.txt")

    # 2. Chrome via nodriver
    browser_args = ["--lang=fr-FR", "--window-size=1280,900"]
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")

    browser = None
    tab = None
    try:
        browser = await uc.start(headless=headless, browser_args=browser_args)
        print("[ACCOUNT-EMAIL] nodriver Chrome started")

        # 3. Navigate
        tab = await browser.get("https://www.tiktok.com/signup/phone-or-email/email")
        await asyncio.sleep(random.uniform(4, 7))

        # 4. Dismiss popups
        await _dismiss_tiktok_popups(tab)
        await asyncio.sleep(random.uniform(1, 2))

        # 5. Birthday — custom React combobox (NOT native <select>)
        # IDs: #Month-options-item-{idx}, #Day-options-item-{idx}, #Year-options-item-{idx}
        month_idx = random.randint(0, 11)
        day = random.randint(1, 28)
        year = random.randint(1985, 1998)
        month_name = MONTHS_FR[month_idx]

        birthday_js = """
        (async () => {
            function clickOption(prefix, text) {
                const opts = document.querySelectorAll('[id^="' + prefix + '-options-item-"]');
                for (const opt of opts) {
                    if (opt.textContent.trim() === text) {
                        opt.click();
                        return true;
                    }
                }
                return false;
            }

            // Month
            const monthBox = document.querySelector('[aria-label*="Mois"]');
            if (!monthBox) return 'no_month_box';
            monthBox.click();
            await new Promise(r => setTimeout(r, 800));
            const mOk = clickOption('Month', '""" + month_name + """');
            await new Promise(r => setTimeout(r, 500));

            // Day
            const dayBox = document.querySelector('[aria-label*="Jour"]');
            if (!dayBox) return 'no_day_box';
            dayBox.click();
            await new Promise(r => setTimeout(r, 800));
            const dOk = clickOption('Day', '""" + str(day) + """');
            await new Promise(r => setTimeout(r, 500));

            // Year
            const yearBox = document.querySelector('[aria-label*="Ann"]');
            if (!yearBox) return 'no_year_box';
            yearBox.click();
            await new Promise(r => setTimeout(r, 800));
            const yOk = clickOption('Year', '""" + str(year) + """');
            await new Promise(r => setTimeout(r, 500));

            return 'M=' + mOk + ' D=' + dOk + ' Y=' + yOk;
        })()
        """

        print(f"[ACCOUNT-EMAIL] Birthday: {month_name} {day} {year}")
        bday_result = await tab.evaluate(birthday_js)
        print(f"  Birthday result: {bday_result}")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Re-dismiss any popup that appeared after combobox interaction
        await _dismiss_tiktok_popups(tab)

        # 6. Type email
        print(f"[ACCOUNT-EMAIL] Typing email: {email}")
        email_el = None
        for sel in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]']:
            try:
                email_el = await tab.select(sel)
                if email_el:
                    break
            except Exception:
                continue

        if not email_el:
            await tab.save_screenshot(f"/tmp/tiktok_nd_no_email_{niche}.png")
            browser.stop()
            return {"success": False, "error": "Email input introuvable (nodriver)"}

        await email_el.click()
        await asyncio.sleep(0.4)
        await email_el.send_keys(email)
        print(f"  Email typed")
        await asyncio.sleep(random.uniform(1, 2))

        # 7. Type password
        print("[ACCOUNT-EMAIL] Typing password...")
        pwd_el = None
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                pwd_el = await tab.select(sel)
                if pwd_el:
                    break
            except Exception:
                continue

        if pwd_el:
            await pwd_el.click()
            await asyncio.sleep(0.3)
            await pwd_el.send_keys(password)
            print(f"  Password typed")
            await asyncio.sleep(random.uniform(1, 2))

        # 8. Click "Envoyer le code"
        print("[ACCOUNT-EMAIL] Clicking 'Envoyer le code'...")
        send_btn = None
        for text in ["Envoyer le code", "Send code", "Envoyer"]:
            try:
                send_btn = await tab.find(text, best_match=True)
                if send_btn:
                    break
            except Exception:
                continue

        if send_btn:
            await send_btn.click()
            print("  'Envoyer le code' clicked")
        else:
            print("  [WARN] Send code button not found")

        await asyncio.sleep(random.uniform(3, 5))

        # 8b. Check rate limit
        page_text = await tab.evaluate("document.body.innerText.slice(0, 3000)") or ""
        for kw in ["trop de tentatives", "réessayez plus tard", "too many attempts", "try again later"]:
            if kw.lower() in page_text.lower():
                print(f"  [BLOCKED] '{kw}'")
                await tab.save_screenshot(f"/tmp/tiktok_nd_blocked_{niche}.png")
                browser.stop()
                return {"success": False, "error": f"TikTok rate limit: {kw}"}

        # 9. Wait for email code
        print("[ACCOUNT-EMAIL] Waiting for email code...")
        otp_code = await mail_client.wait_for_code(email_token, max_wait=120)
        if not otp_code:
            await tab.save_screenshot(f"/tmp/tiktok_nd_no_code_{niche}.png")
            browser.stop()
            return {"success": False, "error": "Timeout email code (120s)"}

        print(f"  Code recu: {otp_code}")

        # 10. Type code
        code_el = None
        for sel in ['input[placeholder*="code" i]', 'input[name="code"]', '[data-e2e="signup-code-input"]']:
            try:
                code_el = await tab.select(sel)
                if code_el:
                    break
            except Exception:
                continue

        if not code_el:
            # Fallback: find all text inputs and pick the one near "code"
            try:
                code_el = await tab.select('input[type="text"]')
            except Exception:
                pass

        if code_el:
            await code_el.click()
            await asyncio.sleep(0.3)
            await code_el.send_keys(otp_code)
            print(f"  Code typed: {otp_code}")
        else:
            print("  [WARN] Code input not found")
            browser.stop()
            return {"success": False, "error": "Code input introuvable"}

        await asyncio.sleep(random.uniform(1.5, 2.5))

        # 11. Click "Suivant" (final submit)
        print("[ACCOUNT-EMAIL] Submitting...")
        submit_btn = None
        for text in ["Suivant", "Next", "S'inscrire", "Sign up"]:
            try:
                submit_btn = await tab.find(text, best_match=True)
                if submit_btn:
                    break
            except Exception:
                continue

        if submit_btn:
            await submit_btn.click()
            print("  Submit clicked")

        await asyncio.sleep(random.uniform(6, 10))

        # 12. Check success
        current_url = await tab.evaluate("window.location.href") or ""
        is_logged_in = (
            "/foryou" in current_url
            or "/following" in current_url
            or "tiktok.com/home" in current_url
            or ("/signup" not in current_url and "tiktok.com" in current_url)
        )

        if not is_logged_in:
            page_text2 = await tab.evaluate("document.body.innerText.slice(0, 2000)") or ""
            await tab.save_screenshot(f"/tmp/tiktok_nd_failed_{niche}.png")
            browser.stop()
            return {"success": False, "error": f"Signup failed, url: {current_url}, page: {page_text2[:200]}"}

        print(f"  Inscription reussie! URL: {current_url}")

        # 13. Save cookies
        await _save_cookies_nodriver(tab, save_cookies_path)
        browser.stop()

        return {
            "success": True,
            "username": username,
            "email": email,
            "password": password,
            "cookies_path": save_cookies_path,
            "niche": niche,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        try:
            if tab:
                await tab.save_screenshot(f"/tmp/tiktok_nd_error_{niche}.png")
        except Exception:
            pass
        if browser:
            try:
                browser.stop()
            except Exception:
                pass
        return {"success": False, "error": str(e)}


async def _select_tiktok_country(page, phone_prefix: str, country_search: str):
    """Selectionne le pays dans le dropdown code pays TikTok.

    Structure TikTok :
      <div role="select" class="..DivAreaLabelContainer..">
        <span>NL +31</span>
      </div>
    Dropdown : liste de <li> avec nom pays + code.
    """
    prefix_num = phone_prefix.lstrip("+")  # "+44" -> "44"

    try:
        # 1. Cliquer le selecteur pays
        area_btn = None
        for sel in [
            'div[role="select"][class*="AreaLabel"]',
            'div[role="select"]',
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    area_btn = el
                    current_text = (await el.text_content()).strip()
                    print(f"  Country current: '{current_text}'")
                    # Si deja le bon pays, pas besoin de changer
                    if f"+{prefix_num}" in current_text:
                        print(f"  Already on +{prefix_num}, skip")
                        return
                    break
            except Exception:
                continue

        if not area_btn:
            print("  Country selector non trouve")
            return

        await area_btn.click(force=True)
        await asyncio.sleep(1.5)

        # 2. Chercher le champ de recherche et taper le NOM DU PAYS
        search_input = None
        for sel in [
            'input[type="search"]',
            'input[placeholder*="earch" i]',
            'input[type="text"]:visible',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.is_visible(timeout=2000):
                    search_input = inp
                    break
            except Exception:
                continue

        if search_input:
            await search_input.fill(country_search)
            await asyncio.sleep(1.5)
            print(f"  Searched: '{country_search}'")
        else:
            print("  No search input")

        # 3. Debug : dump la structure du dropdown pour voir le format des options
        dropdown_debug = await page.evaluate("""
            () => {
                // Trouver tous les elements contenant des noms de pays
                const items = [];
                // Chercher les li, div[role=option], ou tout element petit avec du texte pays
                for (const tag of ['li', 'div[role="option"]', '[class*="Item"]', '[class*="item"]', '[class*="Option"]']) {
                    document.querySelectorAll(tag).forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const text = el.innerText || el.textContent || '';
                        if (rect.height > 0 && rect.height < 80 && text.length > 2 && text.length < 100) {
                            items.push({
                                tag: el.tagName + (el.className ? '.' + el.className.toString().split(' ')[0] : ''),
                                text: text.trim().slice(0, 50),
                                h: Math.round(rect.height),
                            });
                        }
                    });
                }
                return items.slice(0, 8);
            }
        """)
        print(f"  [DROPDOWN] {dropdown_debug}")

        # 4. Cliquer : chercher un element avec le texte EXACT court (nom pays + code)
        country_clicked = False

        clicked_text = await page.evaluate(f"""
            () => {{
                // Chercher TOUS les elements visibles, pas juste li
                const allEls = document.querySelectorAll('*');
                for (const el of allEls) {{
                    const text = (el.innerText || el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    // L'element doit :
                    // - etre visible (height > 0)
                    // - etre petit (un seul item, pas un container)
                    // - contenir le nom du pays
                    // - avoir un texte court (< 80 chars = un seul pays)
                    if (rect.height > 10 && rect.height < 60 &&
                        rect.width > 50 &&
                        text.length < 80 && text.length > 3 &&
                        text.includes('{country_search}')) {{
                        el.click();
                        return text.slice(0, 60);
                    }}
                }}
                return null;
            }}
        """)

        if clicked_text:
            country_clicked = True
            print(f"  Country selected: '{clicked_text}'")

        if not country_clicked:
            # Fallback : keyboard navigation (arrow down + enter)
            print(f"  Trying keyboard: down + enter")
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Enter")
            country_clicked = True

        if not country_clicked:
            print(f"  WARN: Could not select {country_search}")
            await page.keyboard.press("Escape")

        await asyncio.sleep(0.5)

    except Exception as e:
        print(f"  Country selection error: {e}")


async def _close_cookie_banner(page):
    """Ferme le cookie banner TikTok (FR: 'Tout autoriser', EN: 'Accept all')."""
    for sel in [
        'button:has-text("Tout autoriser")',
        'button:has-text("Accept all")',
        'button:has-text("Accepter tout")',
        'button:has-text("Allow all")',
        'button:has-text("Accept")',
        '[data-testid="cookie-banner-accept"]',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                print(f"  Cookie banner closed: {sel}")
                await asyncio.sleep(1)
                return True
        except Exception:
            continue

    # Fallback: JS remove
    await page.evaluate("""
        () => {
            const banners = document.querySelectorAll('[class*="cookie"], [class*="consent"], [id*="cookie"], [id*="consent"]');
            banners.forEach(el => {
                if (el.getBoundingClientRect().height > 50) el.remove();
            });
        }
    """)
    return False


async def _remove_overlays(page):
    """Supprime les popups/overlays qui bloquent les clics."""
    await page.evaluate("""
        () => {
            document.querySelectorAll('[data-floating-ui-portal]').forEach(el => el.remove());
            document.querySelectorAll('[id^="floating-ui"]').forEach(el => el.remove());
            document.querySelectorAll('.tiktok-cookie-banner').forEach(el => el.remove());
            document.querySelectorAll('[class*="modal-mask"]').forEach(el => el.remove());
            document.querySelectorAll('[class*="overlay"]').forEach(el => {
                if (el.style.position === 'fixed' || el.style.position === 'absolute') {
                    el.remove();
                }
            });
        }
    """)


async def _type_like_human(element, text: str):
    for char in text:
        await element.press(char)
        await asyncio.sleep(random.uniform(0.05, 0.15))


async def _save_cookies_netscape(context, output_path: str):
    cookies = await context.cookies()
    with open(output_path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n# Generated by InstaFarm\n\n")
        for cookie in cookies:
            domain = cookie.get("domain", "")
            if not domain.startswith("."):
                domain = "." + domain
            include_subdomain = "TRUE" if domain.startswith(".") else "FALSE"
            path = cookie.get("path", "/")
            secure = "TRUE" if cookie.get("secure", False) else "FALSE"
            expires = str(int(cookie.get("expires", 0))) if cookie.get("expires") else "0"
            name = cookie.get("name", "")
            value = cookie.get("value", "")
            f.write(f"{domain}\t{include_subdomain}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")


def _generate_password() -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(random.choices(chars, k=14))


async def setup_account_in_firebase(account_data: dict, db) -> bool:
    niche = account_data["niche"]
    update_data = {
        "username": account_data["username"],
        "cookies_path": account_data["cookies_path"],
        "status": "warmup",
        "warmup_day": 0,
        "warmup_started_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    if account_data.get("phone"):
        update_data["phone"] = account_data["phone"]
    if account_data.get("email"):
        update_data["email"] = account_data["email"]
    db.collection("tiktok_accounts").document(niche).update(update_data)
    print(f"[ACCOUNT] {niche} enregistre en Firebase — status: warmup")
    return True
