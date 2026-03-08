"""Gestion des cookies TikTok : expiration, validation, alertes."""

import os
from datetime import datetime, timezone


COOKIES_WARNING_DAYS = 3


def parse_cookies_expiry(cookies_path: str) -> datetime | None:
    """Lit un fichier cookies.txt Netscape et retourne la date d'expiration la plus proche."""
    if not cookies_path or not os.path.exists(cookies_path):
        return None

    earliest_expiry = None
    critical_names = {"sessionid", "sid_tt", "uid_tt", "tt_chain_token"}

    try:
        with open(cookies_path, "r") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) < 7:
                    continue
                domain, _, path, secure, expiry_str, name, value = parts[:7]
                if "tiktok.com" in domain and name in critical_names:
                    try:
                        expiry_ts = int(expiry_str)
                        if expiry_ts > 0:
                            expiry_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
                            if earliest_expiry is None or expiry_dt < earliest_expiry:
                                earliest_expiry = expiry_dt
                    except ValueError:
                        continue
    except Exception as e:
        print(f"[COOKIES] Erreur parsing {cookies_path}: {e}")

    return earliest_expiry


async def check_cookies_validity(cookies_path: str) -> dict:
    """Verifie si les cookies sont valides. Retourne un dict de statut."""
    if not cookies_path:
        return {"valid": False, "error": "No cookies path", "days_remaining": 0}

    if not os.path.exists(cookies_path):
        return {"valid": False, "error": f"File not found: {cookies_path}", "days_remaining": 0}

    expiry = parse_cookies_expiry(cookies_path)
    now = datetime.now(timezone.utc)

    if expiry is None:
        # Pas de cookies critiques — verifier age du fichier
        mtime = datetime.fromtimestamp(os.path.getmtime(cookies_path), tz=timezone.utc)
        age_days = (now - mtime).days
        if age_days > 7:
            return {"valid": False, "error": f"Cookies file is {age_days} days old", "days_remaining": 0}
        return {
            "valid": True,
            "expiry": None,
            "days_remaining": 7 - age_days,
            "needs_renewal": age_days > 4,
        }

    days_remaining = (expiry - now).days
    return {
        "valid": days_remaining > 0,
        "expiry": expiry.isoformat(),
        "days_remaining": max(0, days_remaining),
        "needs_renewal": days_remaining <= COOKIES_WARNING_DAYS,
        "error": None if days_remaining > 0 else "Cookies expired",
    }


async def validate_cookies_with_tiktok(cookies_path: str) -> bool:
    """Verifie les cookies via Playwright — ouvre tiktok.com/inbox."""
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
            await _load_cookies_into_context(context, cookies_path)

            page = await context.new_page()
            await page.goto(
                "https://www.tiktok.com/inbox",
                wait_until="networkidle",
                timeout=15000,
            )

            current_url = page.url
            is_valid = "/login" not in current_url and "/signup" not in current_url

            await browser.close()
            return is_valid
    except Exception as e:
        print(f"[COOKIES] Validation Playwright echouee: {e}")
        return False


async def _load_cookies_into_context(context, cookies_path: str):
    """Charge un fichier cookies.txt Netscape dans un contexte Playwright."""
    cookies = []
    with open(cookies_path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) < 7:
                continue
            domain, include_subdomain, path, secure, expiry_str, name, value = parts[:7]
            try:
                expiry_ts = int(expiry_str) if expiry_str else None
            except ValueError:
                expiry_ts = None

            cookie = {
                "name": name,
                "value": value,
                "domain": domain.lstrip("."),
                "path": path,
                "secure": secure.upper() == "TRUE",
                "httpOnly": False,
            }
            if expiry_ts and expiry_ts > 0:
                cookie["expires"] = expiry_ts
            cookies.append(cookie)

    if cookies:
        await context.add_cookies(cookies)


async def alert_expiring_cookies(db):
    """Verifie tous les comptes et alerte si cookies proches de l'expiration."""
    accounts = db.collection("tiktok_accounts").stream()
    alerts = []

    for account_doc in accounts:
        if account_doc.id == "_meta":
            continue
        account = account_doc.to_dict()
        if account.get("status") == "setup" or not account.get("cookies_path"):
            continue

        niche = account_doc.id
        cookies_path = account.get("cookies_path")
        validity = await check_cookies_validity(cookies_path)

        if not validity["valid"]:
            alerts.append(f"COOKIES EXPIRES — {niche}")
            db.collection("tiktok_accounts").document(niche).update({
                "status": "cookies_expired",
                "cookies_valid": False,
            })
        elif validity.get("needs_renewal"):
            days = validity.get("days_remaining", 0)
            alerts.append(f"{niche}: cookies expirent dans {days} jours")

    if alerts:
        from backend.tiktok.alerting import send_alert_telegram
        await send_alert_telegram("\n".join(alerts))
        print("\n".join(alerts))

    return alerts
