"""Warmup progressif des nouveaux comptes TikTok sur 7 jours.

Sans warmup, compte banni en 24-48h.
"""

import asyncio
import random
from datetime import datetime, timezone

WARMUP_PLAN = {
    1: {"watch": 10, "likes": 5, "comments": 0, "dms": 0, "description": "Watch & like only"},
    2: {"watch": 15, "likes": 8, "comments": 0, "dms": 0, "description": "Watch & like"},
    3: {"watch": 10, "likes": 5, "comments": 3, "dms": 0, "description": "Start commenting"},
    4: {"watch": 10, "likes": 5, "comments": 5, "dms": 0, "description": "More comments"},
    5: {"watch": 8, "likes": 4, "comments": 3, "dms": 3, "description": "First DMs (3 max)"},
    6: {"watch": 8, "likes": 4, "comments": 3, "dms": 5, "description": "More DMs (5 max)"},
    7: {"watch": 5, "likes": 3, "comments": 2, "dms": 10, "description": "Near full capacity"},
}

WARMUP_HASHTAGS = {
    "restauration": ["restaurant", "gastronomie", "foodfrance"],
    "coiffure": ["coiffure", "beaute", "salondecoiffure"],
    "btp_artisan": ["bricolage", "renovation", "maison"],
    "dentiste": ["sante", "bienetre", "medecin"],
    "auto_garage": ["voiture", "automobile", "mecanique"],
    "sport_fitness": ["fitness", "sport", "musculation"],
    "immobilier": ["immobilier", "maison", "investissement"],
    "photographe": ["photo", "photographie", "art"],
}


async def run_warmup_day(niche: str, day: int, cookies_path: str) -> dict:
    """Execute le warmup du jour pour un compte."""
    if day not in WARMUP_PLAN:
        return {"success": False, "error": f"Invalid warmup day: {day}"}

    plan = WARMUP_PLAN[day]
    print(f"[WARMUP] {niche} — Jour {day}/7: {plan['description']}")

    results = {"watched": 0, "liked": 0, "commented": 0, "dms": 0, "errors": []}

    try:
        from playwright.async_api import async_playwright
        from backend.tiktok.cookies_manager import _load_cookies_into_context

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = await browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )
            await _load_cookies_into_context(context, cookies_path)
            page = await context.new_page()

            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except ImportError:
                pass

            hashtags = WARMUP_HASHTAGS.get(niche, ["france", "business"])

            # Regarder des videos
            for i in range(plan["watch"]):
                try:
                    hashtag = random.choice(hashtags)
                    await page.goto(
                        f"https://www.tiktok.com/tag/{hashtag}",
                        wait_until="networkidle",
                        timeout=15000,
                    )
                    await asyncio.sleep(random.uniform(8, 15))
                    await page.mouse.wheel(0, random.randint(300, 600))
                    await asyncio.sleep(random.uniform(2, 4))
                    results["watched"] += 1
                except Exception as e:
                    results["errors"].append(f"watch_{i}: {str(e)[:50]}")

            # Liker
            for i in range(plan["likes"]):
                try:
                    like_btn = page.locator('[data-e2e="like-icon"]').first
                    if await like_btn.is_visible(timeout=2000):
                        await like_btn.click()
                        await asyncio.sleep(random.uniform(1, 3))
                        results["liked"] += 1
                except Exception:
                    pass

            await browser.close()

        print(f"  Jour {day} termine — watched:{results['watched']} liked:{results['liked']}")

    except Exception as e:
        results["errors"].append(f"warmup_session: {str(e)[:100]}")
        print(f"  Warmup {niche} jour {day} partiel: {e}")

    return {"success": True, "day": day, "results": results}


async def warmup_daily_progress(db):
    """Appele tous les jours a 10h. Avance d'un jour les comptes en warmup."""
    print("[WARMUP] Progression journaliere...")
    accounts = db.collection("tiktok_accounts").where("status", "==", "warmup").stream()

    for doc in accounts:
        if doc.id == "_meta":
            continue

        data = doc.to_dict()
        niche = doc.id
        current_day = data.get("warmup_day", 0)
        cookies_path = data.get("cookies_path")

        if not cookies_path:
            print(f"  {niche}: pas de cookies, warmup impossible")
            continue

        next_day = current_day + 1
        print(f"  {niche}: warmup jour {next_day}/7")

        await run_warmup_day(niche, next_day, cookies_path)

        if next_day >= 7:
            db.collection("tiktok_accounts").document(niche).update({
                "warmup_day": next_day,
                "status": "active",
                "activated_at": datetime.now(timezone.utc),
            })
            print(f"  {niche}: WARMUP TERMINE — compte ACTIF!")
            from backend.tiktok.alerting import send_alert_telegram
            await send_alert_telegram(
                f"Compte TikTok active!\nNiche: {niche}\nPret a publier et envoyer des DMs",
                level="INFO",
            )
        else:
            db.collection("tiktok_accounts").document(niche).update({
                "warmup_day": next_day,
                "last_warmup_at": datetime.now(timezone.utc),
            })
