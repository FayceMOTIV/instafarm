"""Seed Firebase collections pour le pipeline TikTok.

Lance automatiquement au demarrage — idempotent.
"""

from datetime import datetime, timezone

from backend.tiktok.config import TIKTOK_NICHE_CONFIG

NICHES = list(TIKTOK_NICHE_CONFIG.keys())


def seed_firebase_if_needed(db):
    """Verifie si les collections existent, les initialise sinon."""
    print("[FIREBASE] Verification seed...")

    created = 0

    # 1. tiktok_accounts — 1 document par niche
    for niche in NICHES:
        doc_ref = db.collection("tiktok_accounts").document(niche)
        doc = doc_ref.get()
        if not doc.exists:
            doc_ref.set({
                "niche": niche,
                "username": None,
                "cookies_path": None,
                "status": "setup",
                "warmup_day": 0,
                "warmup_started_at": None,
                "daily_dm_count": 0,
                "daily_dm_reset_at": None,
                "total_dms_sent": 0,
                "total_replies": 0,
                "videos_published": 0,
                "last_health_check": None,
                "cookies_expires_at": None,
                "proxy": None,
                "created_at": datetime.now(timezone.utc),
                "paused": False,
            })
            created += 1
            print(f"  + tiktok_accounts/{niche}")

    # 2. Collections meta (sentinel documents)
    meta_collections = [
        "tiktok_videos",
        "tiktok_dms",
        "tiktok_pipeline_jobs",
        "tiktok_comments",
    ]
    for col in meta_collections:
        meta_ref = db.collection(col).document("_meta")
        if not meta_ref.get().exists:
            meta_ref.set({
                "initialized": True,
                "created_at": datetime.now(timezone.utc),
                "description": f"Sentinel document for {col}",
            })
            created += 1
            print(f"  + {col}/_meta")

    if created == 0:
        print("[FIREBASE] Seed deja en place — rien a faire")
    else:
        print(f"[FIREBASE] Seed termine — {created} documents crees")
