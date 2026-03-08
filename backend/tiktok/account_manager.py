"""Gestion des comptes TikTok : sante, compteurs, rotation."""

import os
from datetime import datetime, timezone

SAFE_LIMITS = {
    "dms_per_day": 20,
    "dms_per_hour": 5,
}


async def get_active_account(niche: str, db) -> dict | None:
    """Retourne le compte actif pour une niche si disponible."""
    doc = db.collection("tiktok_accounts").document(niche).get()
    if not doc.exists:
        return None

    account = doc.to_dict()
    account["id"] = niche

    if account.get("paused"):
        return None
    if account.get("status") != "active":
        return None
    if account.get("daily_dm_count", 0) >= SAFE_LIMITS["dms_per_day"]:
        return None
    if not account.get("cookies_path") or not os.path.exists(account.get("cookies_path", "")):
        return None

    return account


async def increment_dm_count(niche: str, db):
    """Incremente les compteurs DM apres un envoi reussi."""
    ref = db.collection("tiktok_accounts").document(niche)
    doc = ref.get()
    if not doc.exists:
        return

    data = doc.to_dict()
    ref.update({
        "daily_dm_count": data.get("daily_dm_count", 0) + 1,
        "total_dms_sent": data.get("total_dms_sent", 0) + 1,
        "last_dm_at": datetime.now(timezone.utc),
    })


async def reset_daily_counters(db):
    """Appele a minuit — remet daily_dm_count=0 pour tous les comptes."""
    print("[ACCOUNT] Reset compteurs journaliers...")
    accounts = db.collection("tiktok_accounts").stream()
    count = 0

    for doc in accounts:
        if doc.id == "_meta":
            continue
        db.collection("tiktok_accounts").document(doc.id).update({
            "daily_dm_count": 0,
            "daily_dm_reset_at": datetime.now(timezone.utc),
        })
        count += 1

    print(f"  {count} comptes remis a zero")


async def detect_ban(niche: str, db) -> bool:
    """Verifie si un compte est banni via test cookies Playwright."""
    doc = db.collection("tiktok_accounts").document(niche).get()
    if not doc.exists:
        return False

    account = doc.to_dict()
    cookies_path = account.get("cookies_path")
    if not cookies_path or not os.path.exists(cookies_path):
        return False

    from backend.tiktok.cookies_manager import validate_cookies_with_tiktok
    is_valid = await validate_cookies_with_tiktok(cookies_path)

    if not is_valid:
        print(f"[ACCOUNT] {niche}: banni ou cookies expires")
        db.collection("tiktok_accounts").document(niche).update({
            "status": "banned",
            "banned_at": datetime.now(timezone.utc),
        })
        from backend.tiktok.alerting import send_alert_telegram
        await send_alert_telegram(
            f"Compte TikTok BANNI\nNiche: {niche}\nAction: recreer le compte",
            level="ERROR",
        )
        return True

    return False


async def check_accounts_health(db):
    """Verifie la sante de tous les comptes actifs. Appele toutes les heures."""
    print("[ACCOUNT] Health check comptes...")
    accounts = db.collection("tiktok_accounts").stream()

    for doc in accounts:
        if doc.id == "_meta":
            continue
        data = doc.to_dict()
        if data.get("status") not in ("active", "warmup"):
            continue
        await detect_ban(doc.id, db)

    print("  Health check termine")


async def mark_video_published(niche: str, db):
    """Incremente le compteur de videos publiees."""
    ref = db.collection("tiktok_accounts").document(niche)
    doc = ref.get()
    if doc.exists:
        ref.update({
            "videos_published": doc.to_dict().get("videos_published", 0) + 1,
            "last_video_at": datetime.now(timezone.utc),
        })
