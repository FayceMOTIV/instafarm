"""Push notifications PWA via Web Push (VAPID)."""

import json
import os
from datetime import datetime

from backend.database import async_session
from backend.models import SystemLog


# VAPID config
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "admin@instafarm.io")

# Stockage des subscriptions en memoire (en prod : persister en DB ou Redis)
_subscriptions: list[dict] = []


async def _log(tenant_id: int | None, level: str, message: str):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id, level=level, module="notifications",
            message=message, details="{}",
        ))
        await session.commit()


def register_subscription(subscription: dict):
    """Enregistre une subscription push PWA."""
    # Eviter les doublons
    endpoint = subscription.get("endpoint", "")
    for existing in _subscriptions:
        if existing.get("endpoint") == endpoint:
            return
    _subscriptions.append(subscription)


def unregister_subscription(endpoint: str):
    """Supprime une subscription push."""
    _subscriptions[:] = [s for s in _subscriptions if s.get("endpoint") != endpoint]


async def send_push_notification(
    title: str,
    body: str,
    tenant_id: int | None = None,
    url: str | None = None,
    tag: str | None = None,
) -> int:
    """
    Envoie une push notification a toutes les subscriptions enregistrees.
    Retourne le nombre de notifications envoyees avec succes.
    """
    if not VAPID_PRIVATE_KEY:
        await _log(tenant_id, "WARNING", "VAPID_PRIVATE_KEY non configure — push desactivee")
        return 0

    if not _subscriptions:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url or "/pwa/",
        "tag": tag or "instafarm",
        "timestamp": datetime.utcnow().isoformat(),
    }, ensure_ascii=False)

    sent = 0
    failed_endpoints: list[str] = []

    try:
        from pywebpush import webpush, WebPushException

        vapid_claims = {
            "sub": f"mailto:{VAPID_EMAIL}",
        }

        for sub in _subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=vapid_claims,
                )
                sent += 1
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    # Subscription expiree — la supprimer
                    failed_endpoints.append(sub.get("endpoint", ""))
                else:
                    await _log(tenant_id, "ERROR", f"Push echouee: {e}")

    except ImportError:
        await _log(tenant_id, "WARNING", "pywebpush non installe")
        return 0

    # Cleanup subscriptions expirees
    for endpoint in failed_endpoints:
        unregister_subscription(endpoint)

    if sent > 0:
        await _log(tenant_id, "INFO", f"Push envoyee: {title} ({sent} devices)")

    return sent


async def send_morning_report_push(tenant_id: int, report: str) -> int:
    """Push du rapport matin a 08h00."""
    return await send_push_notification(
        title="Rapport InstaFarm",
        body=report[:200],  # Limite push notification
        tenant_id=tenant_id,
        url="/pwa/#dashboard",
        tag="morning-report",
    )


async def send_hot_prospect_push(tenant_id: int, username: str, niche_name: str) -> int:
    """Push quand un prospect est detecte comme interesse."""
    return await send_push_notification(
        title=f"Prospect chaud ! {niche_name}",
        body=f"@{username} est interesse — repondre maintenant",
        tenant_id=tenant_id,
        url="/pwa/#inbox",
        tag=f"hot-prospect-{username}",
    )


async def send_alert_push(tenant_id: int | None, service: str, error: str) -> int:
    """Push pour alertes critiques (watchdog)."""
    return await send_push_notification(
        title=f"ALERTE: {service}",
        body=error[:200],
        tenant_id=tenant_id,
        url="/pwa/#control",
        tag=f"alert-{service}",
    )
