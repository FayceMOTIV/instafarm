"""
Playwright Login — Login Instagram web + sauvegarde cookies en DB.

Gere :
- Cookie consent ("Autoriser tous les cookies")
- Terms/consent pages ("Suivant" → "Accepter")
- Dialogs "Plus tard"
- Sauvegarde + restauration cookies
"""

import json
import logging
from datetime import datetime

from sqlalchemy import select

from backend.database import async_session
from backend.models import IgAccount, Proxy

logger = logging.getLogger("instafarm.pw_login")

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)


async def _get_account_and_proxy(account_id: int) -> tuple[IgAccount | None, Proxy | None]:
    """Charge compte + proxy depuis DB."""
    async with async_session() as session:
        result = await session.execute(
            select(IgAccount).where(IgAccount.id == account_id)
        )
        account = result.scalars().first()
        if not account:
            return None, None

        proxy = None
        if account.proxy_id:
            result = await session.execute(
                select(Proxy).where(Proxy.id == account.proxy_id)
            )
            proxy = result.scalars().first()

        return account, proxy


async def _dismiss_cookie_consent(page) -> bool:
    """Click le bouton consent cookies via JS (plus fiable que locators Playwright)."""
    import asyncio

    clicked = await page.evaluate('''() => {
        const btns = document.querySelectorAll("button");
        for (const btn of btns) {
            const txt = btn.textContent.trim();
            if (txt === "Autoriser tous les cookies"
                || txt === "Allow all cookies"
                || txt === "Tout autoriser"
                || txt === "Allow essential and optional cookies") {
                btn.click();
                return true;
            }
        }
        return false;
    }''')
    if clicked:
        await asyncio.sleep(2)
    return clicked


async def _handle_consent_and_terms(page) -> None:
    """Gere les pages de consentement cookies et terms."""
    import asyncio

    for _ in range(5):
        handled = False
        url = page.url

        # Cookie consent — JS click (le popup peut etre dans un React lazy-load)
        if await _dismiss_cookie_consent(page):
            continue

        # Terms / consent pages
        if "/consent/" in url or "terms" in url:
            for btn_name in ["Suivant", "Accepter", "Next", "Accept"]:
                try:
                    btn = page.get_by_role("button", name=btn_name)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(1.5)
                        handled = True
                        break
                except Exception:
                    continue
            if handled:
                continue

        # "Plus tard" / "Not Now" dialogs
        for btn_name in ["Plus tard", "Not Now", "Pas maintenant"]:
            try:
                btn = page.get_by_role("button", name=btn_name)
                if await btn.is_visible(timeout=1200):
                    await btn.click()
                    await asyncio.sleep(1)
                    handled = True
                    break
            except Exception:
                continue
        if handled:
            continue

        # Rien trouvé — on sort
        break


async def _save_cookies_to_db(account_id: int, cookies: list) -> None:
    """Sauvegarde cookies en DB."""
    async with async_session() as session:
        result = await session.execute(
            select(IgAccount).where(IgAccount.id == account_id)
        )
        acc = result.scalars().first()
        if acc:
            acc.session_data = json.dumps(cookies)
            acc.cookies_updated_at = datetime.utcnow()
            acc.last_login = datetime.utcnow()
            await session.commit()


async def login_and_save_session(account_id: int) -> bool:
    """
    Login complet Playwright + sauvegarde cookies en DB.

    Args:
        account_id: ID du compte IgAccount

    Returns:
        True si login reussi
    """
    import asyncio
    from playwright.async_api import async_playwright

    account, proxy = await _get_account_and_proxy(account_id)
    if not account:
        logger.error(f"Compte {account_id} non trouve")
        return False

    pw = await async_playwright().start()

    launch_opts = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if proxy:
        launch_opts["proxy"] = {
            "server": f"http://{proxy.host}:{proxy.port}",
            "username": proxy.username or "",
            "password": proxy.password or "",
        }

    browser = await pw.chromium.launch(**launch_opts)
    context = await browser.new_context(
        user_agent=CHROME_UA,
        viewport={"width": 1280, "height": 800},
        locale="fr-FR",
    )
    page = await context.new_page()

    try:
        # Login page
        await page.goto(
            "https://www.instagram.com/accounts/login/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        # Attendre que React rende le DOM (inputs login)
        await asyncio.sleep(5)

        # Handle cookie consent (via JS pour fiabilite)
        await _handle_consent_and_terms(page)
        await asyncio.sleep(1)

        # Attendre que les champs login soient visibles
        username_input = page.locator('input[name="username"], input[name="email"]').first
        password_input = page.locator('input[name="password"], input[name="pass"]').first

        try:
            await username_input.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.warning(f"[Login] @{account.username} champ username non visible")
            return False

        await username_input.fill(account.username)
        await asyncio.sleep(0.8)
        await password_input.fill(account.password)
        await asyncio.sleep(0.8)

        # Submit — Instagram cache le bouton submit, on utilise Enter
        await password_input.press("Enter")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(5)

        # Handle post-login pages
        await _handle_consent_and_terms(page)

        # Navigate home if stuck on API/redirect
        if "/api/" in page.url:
            await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

        # Final consent/dialog handling
        await _handle_consent_and_terms(page)

        # Verify login success
        is_logged = (
            "instagram.com" in page.url
            and "/accounts/login" not in page.url
        )

        if is_logged:
            # Save cookies
            cookies = await context.cookies()
            await _save_cookies_to_db(account.id, cookies)
            logger.info(f"[Login] @{account.username} login OK + cookies saved ({len(cookies)} cookies)")
            return True
        else:
            logger.warning(f"[Login] @{account.username} login echoue (url={page.url})")
            return False

    except Exception as e:
        logger.error(f"[Login] @{account.username} erreur: {e}")
        return False

    finally:
        await browser.close()
        await pw.stop()


async def login_from_session(account_id: int) -> tuple:
    """
    Login rapide depuis cookies sauvegardes.
    Retourne (pw, browser, context, page) pour reutilisation.
    Si session expiree, fait un login complet.

    Returns:
        (playwright, browser, context, page) ou (None, None, None, None) si echec
    """
    import asyncio
    from playwright.async_api import async_playwright

    account, proxy = await _get_account_and_proxy(account_id)
    if not account:
        return None, None, None, None

    pw = await async_playwright().start()

    launch_opts = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if proxy:
        launch_opts["proxy"] = {
            "server": f"http://{proxy.host}:{proxy.port}",
            "username": proxy.username or "",
            "password": proxy.password or "",
        }

    browser = await pw.chromium.launch(**launch_opts)
    context = await browser.new_context(
        user_agent=CHROME_UA,
        viewport={"width": 1280, "height": 800},
        locale="fr-FR",
    )

    # Inject saved cookies
    if account.session_data:
        try:
            cookies = json.loads(account.session_data)
            await context.add_cookies(cookies)
        except Exception:
            pass

    page = await context.new_page()
    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
    await asyncio.sleep(3)

    await _handle_consent_and_terms(page)

    # Check if session valid
    if "/accounts/login" in page.url:
        logger.info(f"[Login] @{account.username} session expiree, re-login...")
        await browser.close()
        await pw.stop()

        # Full re-login
        success = await login_and_save_session(account_id)
        if not success:
            return None, None, None, None

        # Re-open with fresh cookies
        return await login_from_session(account_id)

    # Update cookies
    cookies = await context.cookies()
    await _save_cookies_to_db(account.id, cookies)
    logger.info(f"[Login] @{account.username} session restauree OK")

    return pw, browser, context, page
