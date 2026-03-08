"""Creation automatisee de comptes TikTok.

Stack : 5sim.net (SMS) + SadCaptcha (CAPTCHA) + playwright-stealth.
Cout par compte : ~$0.02.
"""

import asyncio
import os
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

FIVESIM_API_KEY = os.getenv("FIVESIM_API_KEY", "")
SADCAPTCHA_API_KEY = os.getenv("SADCAPTCHA_API_KEY", "")

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


class FiveSimClient:
    """Client API 5sim.net pour numeros virtuels SMS."""

    BASE_URL = "https://5sim.net/v1"

    def __init__(self, api_key: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    async def get_balance(self) -> float:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.BASE_URL}/user/profile", headers=self.headers)
            if r.status_code == 200:
                return r.json().get("balance", 0)
            return 0

    async def buy_number_tiktok(self, country: str = "france") -> dict | None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/user/buy/activation/{country}/any/tiktok",
                headers=self.headers,
            )
            if r.status_code != 200:
                print(f"[5SIM] Buy failed: {r.status_code} — {r.text[:200]}")
                return None

            data = r.json()
            phone = data.get("phone", "")
            if not phone.startswith("+"):
                phone = "+" + phone

            return {
                "order_id": data["id"],
                "phone": phone,
                "operator": data.get("operator"),
                "price": data.get("price", 0),
            }

    async def wait_for_sms(self, order_id: int, max_wait: int = 120) -> str | None:
        async with httpx.AsyncClient() as client:
            for attempt in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(
                    f"{self.BASE_URL}/user/check/{order_id}",
                    headers=self.headers,
                )
                if r.status_code != 200:
                    continue

                data = r.json()
                status = data.get("status", "")

                if status == "RECEIVED":
                    sms_list = data.get("sms", [])
                    if sms_list:
                        sms_text = sms_list[0].get("text", "")
                        code = re.search(r"\b(\d{4,6})\b", sms_text)
                        if code:
                            return code.group(1)
                elif status in ("BANNED", "EXPIRED", "CANCELED"):
                    print(f"[5SIM] Order {order_id} status={status}")
                    return None

                print(f"  SMS wait... ({attempt * 5}s/{max_wait}s) status={status}")

        return None

    async def cancel_number(self, order_id: int):
        async with httpx.AsyncClient() as client:
            await client.get(
                f"{self.BASE_URL}/user/cancel/{order_id}",
                headers=self.headers,
            )


async def create_tiktok_account(
    niche: str,
    proxy: str | None = None,
    save_cookies_path: str | None = None,
    headless: bool = True,
) -> dict:
    """Cree un compte TikTok complet. Retourne {success, username, phone, cookies_path, error}."""
    if not FIVESIM_API_KEY:
        return {"success": False, "error": "FIVESIM_API_KEY not configured"}

    fivesim = FiveSimClient(FIVESIM_API_KEY)

    balance = await fivesim.get_balance()
    if balance < 0.05:
        return {"success": False, "error": f"5sim balance too low: ${balance:.2f}"}

    print(f"[ACCOUNT] 5sim balance: ${balance:.2f}")

    username_base = random.choice(NICHE_USERNAMES.get(niche, ["ProFrance"]))
    username = f"{username_base}{random.randint(10, 99)}"
    password = _generate_password()

    print("[ACCOUNT] Achat numero TikTok FR...")
    number_info = await fivesim.buy_number_tiktok(country="france")
    if not number_info:
        return {"success": False, "error": "Failed to buy 5sim number"}

    phone = number_info["phone"]
    order_id = number_info["order_id"]
    print(f"  Numero: {phone} (order: {order_id})")

    if not save_cookies_path:
        cookies_dir = Path("backend/tiktok/cookies")
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
            await page.goto("https://www.tiktok.com/signup", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 3))

            # 2. Selectionner telephone
            try:
                phone_btn = page.locator('text="Use phone or email"').first
                if await phone_btn.is_visible(timeout=3000):
                    await phone_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            try:
                phone_tab = page.locator('[data-e2e="signup-phone-tab"]').first
                if not await phone_tab.is_visible(timeout=2000):
                    phone_tab = page.locator('text="Phone"').first
                if await phone_tab.is_visible(timeout=2000):
                    await phone_tab.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # 3. Date de naissance
            try:
                month_select = page.locator('[data-e2e="birthday-month"]').first
                if await month_select.is_visible(timeout=3000):
                    await month_select.select_option(str(random.randint(1, 12)))
                    await asyncio.sleep(0.5)
                    day_select = page.locator('[data-e2e="birthday-day"]').first
                    await day_select.select_option(str(random.randint(1, 28)))
                    await asyncio.sleep(0.5)
                    year_select = page.locator('[data-e2e="birthday-year"]').first
                    await year_select.select_option(str(random.randint(1985, 1998)))
                    await asyncio.sleep(0.5)
                    next_btn = page.locator('[data-e2e="birthday-continue"]').first
                    if await next_btn.is_visible(timeout=2000):
                        await next_btn.click()
                        await asyncio.sleep(1.5)
            except Exception as e:
                print(f"  Birthday step: {e}")

            # 4. Numero de telephone
            print(f"[ACCOUNT] Saisie numero {phone}...")
            try:
                phone_input = page.locator('[data-e2e="signup-phone-input"]').first
                if not await phone_input.is_visible(timeout=3000):
                    phone_input = page.locator('input[placeholder*="phone" i]').first

                phone_local = phone.replace("+33", "0")
                await phone_input.click()
                await asyncio.sleep(0.5)
                await _type_like_human(phone_input, phone_local)
                await asyncio.sleep(1)
            except Exception as e:
                await page.screenshot(path=f"/tmp/tiktok_signup_debug_{niche}.png")
                await browser.close()
                await fivesim.cancel_number(order_id)
                return {"success": False, "error": f"Phone input failed: {e}"}

            # 5. CAPTCHA
            print("[ACCOUNT] CAPTCHA check...")
            await _solve_captcha_if_present(page)

            # 6. Envoyer OTP
            send_code_btn = page.locator('[data-e2e="signup-send-code-btn"]').first
            if not await send_code_btn.is_visible(timeout=3000):
                send_code_btn = page.locator('text="Send code"').first
            if await send_code_btn.is_visible(timeout=3000):
                await send_code_btn.click()
                print("[ACCOUNT] Code SMS envoye...")

            # 7. Attendre OTP
            otp_code = await fivesim.wait_for_sms(order_id, max_wait=120)
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
            await fivesim.cancel_number(order_id)
            return {"success": False, "error": str(e)}


async def _solve_captcha_if_present(page) -> bool:
    if not SADCAPTCHA_API_KEY:
        return False
    try:
        from tiktok_captcha_solver import AsyncSadCaptchaSolver
        solver = AsyncSadCaptchaSolver(sadcaptcha_api_key=SADCAPTCHA_API_KEY)
        await solver.solve_captcha_if_present(page, max_attempts=3)
        return True
    except Exception as e:
        print(f"  CAPTCHA solver: {e}")
        return False


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
