"""Creation automatisee de comptes TikTok.

Stack : GrizzlySMS (OTP) + CapSolver (CAPTCHA) + playwright-stealth.
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

SMS_API_KEY = os.getenv("SMS_ACTIVATE_KEY", "")
SMS_API_URL = os.getenv("SMS_API_URL", "https://api.grizzlysms.com/stubs/handler_api.php")
CAPSOLVER_KEY = os.getenv("CAPSOLVER_KEY", "")

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
]


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

async def create_tiktok_account(
    niche: str,
    proxy: str | None = None,
    save_cookies_path: str | None = None,
    headless: bool = True,
) -> dict:
    """Cree un compte TikTok complet. Retourne {success, username, phone, cookies_path, error}."""
    if not SMS_API_KEY:
        return {"success": False, "error": "SMS_ACTIVATE_KEY not configured"}

    sms_client = GrizzlySMSClient(SMS_API_KEY, SMS_API_URL)

    balance = await sms_client.get_balance()
    if balance < 5:
        return {"success": False, "error": f"SMS balance trop faible: {balance} RUB"}

    print(f"[ACCOUNT] SMS balance: {balance} RUB")

    username_base = random.choice(NICHE_USERNAMES.get(niche, ["ProFrance"]))
    username = f"{username_base}{random.randint(10, 99)}"
    password = _generate_password()

    print("[ACCOUNT] Achat numero TikTok FR...")
    number_info = await sms_client.buy_number(service="lf", country="78")
    if not number_info:
        return {"success": False, "error": "Echec achat numero GrizzlySMS"}

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
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )

        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            pass

        try:
            # 1. Page inscription
            print("[ACCOUNT] Navigation signup...")
            await page.goto(
                "https://www.tiktok.com/signup/phone-or-email/phone",
                wait_until="networkidle",
                timeout=30000,
            )
            await asyncio.sleep(random.uniform(2, 4))
            await page.screenshot(path="/tmp/tiktok_step1_loaded.png")
            print(f"  Step 1 URL: {page.url}")

            # 2. Accepter cookies/consent + supprimer overlays
            for consent_sel in [
                'button:has-text("Accept all")',
                'button:has-text("Accepter tout")',
                'button:has-text("Accepter")',
                'button:has-text("Allow all")',
                'button:has-text("Allow")',
                '[data-testid="cookie-banner-accept"]',
                'button:has-text("Accept")',
            ]:
                try:
                    btn = page.locator(consent_sel).first
                    if await btn.is_visible(timeout=1500):
                        await btn.click()
                        await asyncio.sleep(1)
                        print(f"  Consent clique: {consent_sel}")
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

            phone_local = phone.replace("+33", "0")
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
            await asyncio.sleep(2)
            await page.screenshot(path="/tmp/tiktok_step6_sendcode.png")

            # 7. Attendre OTP via GrizzlySMS
            otp_code = await sms_client.wait_for_sms(order_id, max_wait=120)
            if not otp_code:
                await browser.close()
                return {"success": False, "error": "Timeout waiting for SMS OTP"}

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
    db.collection("tiktok_accounts").document(niche).update({
        "username": account_data["username"],
        "phone": account_data["phone"],
        "cookies_path": account_data["cookies_path"],
        "status": "warmup",
        "warmup_day": 0,
        "warmup_started_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    })
    print(f"[ACCOUNT] {niche} enregistre en Firebase — status: warmup")
    return True
