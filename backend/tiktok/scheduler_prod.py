"""Scheduler production InstaFarm — tourne 24/7 sur Railway.

Jobs :
- Publier video selon niche (horaires configures)
- Scanner commentaires toutes les 30min
- Verifier sante comptes toutes les heures
- Warmup journalier a 10h
- Reset compteurs a minuit
- Resume quotidien a 12h
"""

import pytz
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.tiktok.config import TIKTOK_NICHE_CONFIG

PARIS_TZ = pytz.timezone("Europe/Paris")


def setup_scheduler(db) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=PARIS_TZ)

    # --- VIDEOS : 1 par niche par jour ---
    for niche, config in TIKTOK_NICHE_CONFIG.items():
        hour = config["publish_hour"]
        minute = config["publish_minute"]

        def make_video_job(n):
            async def job():
                from backend.tiktok.pipeline import run_video_pipeline_safe
                print(f"[SCHED {datetime.now().strftime('%H:%M')}] Pipeline video : {n}")
                await run_video_pipeline_safe(niche=n, publish=True)
            return job

        scheduler.add_job(
            make_video_job(niche),
            CronTrigger(hour=hour, minute=minute, timezone=PARIS_TZ),
            id=f"video_{niche}",
            name=f"Video TikTok — {niche}",
            max_instances=1,
            misfire_grace_time=600,
        )
        print(f"  [SCHED] {niche}: video a {hour:02d}h{minute:02d}")

    # --- COMMENTAIRES : scan toutes les 30 minutes ---
    async def scan_comments_all_niches():
        print(f"[SCHED {datetime.now().strftime('%H:%M')}] Scan commentaires...")
        accounts = db.collection("tiktok_accounts").where("status", "==", "active").stream()

        for account_doc in accounts:
            if account_doc.id == "_meta":
                continue
            account = account_doc.to_dict()
            niche = account_doc.id
            username = account.get("username")
            cookies_path = account.get("cookies_path")
            if not username or not cookies_path:
                continue
            try:
                from backend.tiktok.comment_detector import scan_and_detect
                from backend.tiktok.dm_engine import send_tiktok_dm, generate_dm_message
                from backend.tiktok.account_manager import get_active_account, increment_dm_count

                triggers = await scan_and_detect(username, niche, db, max_videos=5)
                if triggers:
                    print(f"  [SCHED] {niche}: {len(triggers)} triggers")
                    for trigger in triggers:
                        active_account = await get_active_account(niche, db)
                        if not active_account:
                            break
                        message = generate_dm_message(
                            trigger["username"],
                            trigger.get("comment", ""),
                            trigger.get("keyword", ""),
                            niche,
                        )
                        success = await send_tiktok_dm(
                            trigger["username"], message, cookies_path
                        )
                        if success:
                            await increment_dm_count(niche, db)
                            db.collection("tiktok_dms").add({
                                "niche": niche,
                                "recipient_username": trigger["username"],
                                "message": message,
                                "trigger_keyword": trigger.get("keyword", ""),
                                "status": "sent",
                                "sent_at": datetime.now(timezone.utc).isoformat(),
                            })
            except ImportError:
                pass  # comment_detector/dm_engine pas encore crees
            except Exception as e:
                print(f"  [SCHED] Scan {niche} failed: {e}")

        # Scanner inbox pour les reponses
        try:
            from backend.tiktok.inbox_scanner import process_inbox_replies
            await process_inbox_replies(db)
        except ImportError:
            pass
        except Exception as e:
            print(f"  [SCHED] Inbox scan failed: {e}")

    scheduler.add_job(
        scan_comments_all_niches,
        IntervalTrigger(minutes=30),
        id="scan_comments",
        name="Scan commentaires TikTok",
        max_instances=1,
    )

    # --- SANTE COMPTES : toutes les heures ---
    async def check_accounts_health():
        from backend.tiktok.cookies_manager import alert_expiring_cookies
        from backend.tiktok.account_manager import check_accounts_health as _check

        print(f"[SCHED {datetime.now().strftime('%H:%M')}] Health check comptes...")
        await alert_expiring_cookies(db)
        await _check(db)

    scheduler.add_job(
        check_accounts_health,
        IntervalTrigger(hours=1),
        id="health_check",
        name="Health check comptes",
    )

    # --- WARMUP : tous les jours a 10h ---
    async def warmup_progress():
        from backend.tiktok.warmup_engine import warmup_daily_progress
        await warmup_daily_progress(db)

    scheduler.add_job(
        warmup_progress,
        CronTrigger(hour=10, minute=0, timezone=PARIS_TZ),
        id="warmup_daily",
        name="Warmup journalier comptes",
        max_instances=1,
    )

    # --- RESET JOURNALIER : minuit ---
    async def daily_reset():
        from backend.tiktok.account_manager import reset_daily_counters
        await reset_daily_counters(db)

    scheduler.add_job(
        daily_reset,
        CronTrigger(hour=0, minute=0, timezone=PARIS_TZ),
        id="daily_reset",
        name="Reset compteurs journaliers",
    )

    # --- RESUME QUOTIDIEN : 12h00 ---
    async def daily_summary():
        from backend.tiktok.alerting import alert_daily_summary
        stats = {}
        for niche in TIKTOK_NICHE_CONFIG:
            stats[niche] = {"videos": 0, "dms": 0, "replies": 0}
            try:
                today = datetime.now(PARIS_TZ).date().isoformat()
                videos = list(db.collection("tiktok_videos")
                    .where("niche", "==", niche)
                    .where("date", ">=", today)
                    .stream())
                dms = list(db.collection("tiktok_dms")
                    .where("niche", "==", niche)
                    .where("sent_at", ">=", today)
                    .stream())
                stats[niche] = {"videos": len(videos), "dms": len(dms)}
            except Exception:
                pass
        await alert_daily_summary(stats)

    scheduler.add_job(
        daily_summary,
        CronTrigger(hour=12, minute=0, timezone=PARIS_TZ),
        id="daily_summary",
        name="Resume quotidien",
    )

    return scheduler
