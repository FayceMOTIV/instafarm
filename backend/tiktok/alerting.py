"""Systeme d'alertes InstaFarm — Telegram + log fallback."""

import os
from datetime import datetime

import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


async def send_alert_telegram(message: str, level: str = "WARNING") -> bool:
    """Envoie une alerte sur Telegram. Fallback: print."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[ALERT-{level}] {message}")
        return False

    emoji = {"ERROR": "\U0001f534", "WARNING": "\U0001f7e0", "INFO": "\U0001f7e2"}.get(level, "\u26aa")
    text = (
        f"{emoji} *InstaFarm Alert*\n\n{message}\n\n"
        f"_{datetime.now().strftime('%d/%m %H:%M')}_"
    )

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            return r.status_code == 200
    except Exception as e:
        print(f"[ALERT] Telegram failed: {e}")
        return False


async def alert_pipeline_failure(niche: str, error: str, job_id: str = None):
    """Alerte quand le pipeline video echoue."""
    msg = f"Pipeline FAILED\nNiche: {niche}\nJob: {job_id or 'unknown'}\nError: {error[:200]}"
    await send_alert_telegram(msg, level="ERROR")


async def alert_upload_failure(niche: str, error: str):
    """Alerte quand l'upload TikTok echoue."""
    msg = f"Upload FAILED\nNiche: {niche}\nError: {error[:200]}"
    await send_alert_telegram(msg, level="ERROR")


async def alert_daily_summary(stats: dict):
    """Resume quotidien envoye a midi."""
    lines = ["*Resume InstaFarm du jour*\n"]
    for niche, data in stats.items():
        lines.append(f"*{niche}*")
        lines.append(f"  Videos: {data.get('videos', 0)}")
        lines.append(f"  DMs: {data.get('dms', 0)}")
        lines.append(f"  Reponses: {data.get('replies', 0)}")
        lines.append("")
    await send_alert_telegram("\n".join(lines), level="INFO")
