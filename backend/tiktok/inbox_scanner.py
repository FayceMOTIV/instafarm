"""Scan des reponses aux DMs TikTok.

Detecte les leads qui ont repondu, genere une suggestion de reponse avec Groq.
"""

import os
from datetime import datetime, timezone

from playwright.async_api import async_playwright

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


async def scan_dm_inbox(niche: str, cookies_path: str, db) -> list:
    """Ouvre l'inbox TikTok du compte et recupere les nouvelles reponses."""
    if not cookies_path or not os.path.exists(cookies_path):
        return []

    new_replies = []

    try:
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
            )
            await _load_cookies_into_context(context, cookies_path)
            page = await context.new_page()

            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except ImportError:
                pass

            await page.goto(
                "https://www.tiktok.com/inbox",
                wait_until="networkidle",
                timeout=20000,
            )

            if "/login" in page.url or "/signup" in page.url:
                print(f"  {niche}: session expiree pour inbox scan")
                await browser.close()
                return []

            # Recuperer les conversations avec messages non lus
            conversations = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('[data-e2e="message-item"]');
                    return Array.from(items).slice(0, 20).map(item => ({
                        username: item.querySelector('[data-e2e="message-user-name"]')?.textContent?.trim() || '',
                        lastMessage: item.querySelector('[data-e2e="message-preview"]')?.textContent?.trim() || '',
                        hasUnread: item.querySelector('[data-e2e="unread-badge"]') !== null,
                    }));
                }
            """)

            for conv in conversations:
                if not conv.get("hasUnread") or not conv.get("username"):
                    continue

                username = conv["username"]
                last_msg = conv["lastMessage"]

                existing = db.collection("tiktok_dms").where(
                    "recipient_username", "==", username
                ).where("niche", "==", niche).limit(1).get()

                dm_docs = list(existing)
                if not dm_docs:
                    continue

                dm_data = dm_docs[0].to_dict()
                if dm_data.get("status") == "sent" and last_msg:
                    new_replies.append({
                        "dm_id": dm_docs[0].id,
                        "username": username,
                        "niche": niche,
                        "their_reply": last_msg,
                        "original_keyword": dm_data.get("trigger_keyword", ""),
                    })

            await browser.close()

    except Exception as e:
        print(f"  Inbox scan {niche}: {e}")

    return new_replies


async def generate_reply_suggestion(reply_data: dict) -> str:
    """Utilise Groq pour generer une suggestion de reponse."""
    if not GROQ_API_KEY:
        return _fallback_reply(reply_data["niche"])

    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

    prompt = (
        f'Tu es un commercial chaleureux qui aide des professionnels francais.\n'
        f'Un prospect dans la niche "{reply_data["niche"]}" a repondu a ton DM TikTok.\n\n'
        f'Sa reponse : "{reply_data["their_reply"]}"\n'
        f'Keyword qui a declenche le DM : "{reply_data["original_keyword"]}"\n\n'
        f'Genere une reponse courte (2-3 lignes max) qui :\n'
        f'1. Repond directement a ce qu\'il a dit\n'
        f'2. Pose UNE question pour mieux comprendre son besoin\n'
        f'3. Reste naturel, pas commercial\n\n'
        f'Reponds UNIQUEMENT avec le message, sans explication.'
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  Groq reply suggestion: {e}")
        return _fallback_reply(reply_data["niche"])


def _fallback_reply(niche: str) -> str:
    fallbacks = {
        "restauration": "Super ! Dis-moi, tu geres combien de couverts par service en ce moment ?",
        "coiffure": "Cool ! Tu travailles en salon ou a ton compte ?",
        "btp_artisan": "Parfait ! C'est quoi ta specialite principale ?",
        "dentiste": "Merci de ta reponse ! Tu cherches a developper quelle partie de ton cabinet ?",
        "auto_garage": "Super ! Tu as combien d'entrees atelier par semaine environ ?",
        "sport_fitness": "Top ! Tu coaches en presentiel, en ligne, ou les deux ?",
        "immobilier": "Excellent ! Tu travailles en agence ou en tant que mandataire ?",
        "photographe": "Genial ! Tu es specialise dans quel type de photo principalement ?",
    }
    return fallbacks.get(niche, "Super ! Dis-moi en plus sur ton activite ?")


async def process_inbox_replies(db):
    """Traite les nouvelles reponses pour tous les comptes actifs."""
    accounts = db.collection("tiktok_accounts").where("status", "==", "active").stream()

    for doc in accounts:
        if doc.id == "_meta":
            continue
        data = doc.to_dict()
        niche = doc.id
        cookies_path = data.get("cookies_path")

        if not cookies_path:
            continue

        replies = await scan_dm_inbox(niche, cookies_path, db)

        for reply in replies:
            suggestion = await generate_reply_suggestion(reply)

            db.collection("tiktok_dms").document(reply["dm_id"]).update({
                "status": "replied",
                "their_reply": reply["their_reply"],
                "reply_suggestion": suggestion,
                "replied_at": datetime.now(timezone.utc),
            })

            print(f"  {niche} @{reply['username']}: reponse detectee")

        if replies:
            from backend.tiktok.alerting import send_alert_telegram
            await send_alert_telegram(
                f"{len(replies)} nouvelles reponses DM\nNiche: {niche}",
                level="INFO",
            )
