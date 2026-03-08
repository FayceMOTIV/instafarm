"""Detection de commentaires triggers sur les videos TikTok.

2 couches de detection :
  1. Keywords exacts (rapide, gratuit)
  2. IA Groq pour commentaires sans keyword exact mais avec intention d'achat
"""

import os
import asyncio
import random
from datetime import datetime, timezone

from playwright.async_api import async_playwright

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Keywords declencheurs par niche
TRIGGER_KEYWORDS = {
    "restauration": [
        "MENU", "CARTE", "TARIF", "GUIDE", "OUI", "INFO", "VEUX",
        "JE VEUX", "INTERESSE", "M'INTERESSE", "ENVOI", "ENVOIE",
    ],
    "coiffure": [
        "PRIX", "PROMO", "GUIDE", "INFO", "OUI", "DISPO", "TARIF",
        "AGENDA", "RDV",
    ],
    "dentiste": [
        "RDV", "INFO", "GUIDE", "CONTACT", "OUI", "INTERESSE", "COMMENT",
    ],
    "btp_artisan": [
        "DEVIS", "GUIDE", "PRIX", "INFO", "OUI", "DISPO", "CHANTIER",
    ],
    "immobilier": [
        "GUIDE", "ASTUCE", "INFO", "MANDAT", "OUI", "FORMATION",
    ],
    "photographe": [
        "TARIF", "PACK", "INFO", "GUIDE", "OUI", "DISPO", "PRIX",
    ],
    "auto_garage": [
        "DEVIS", "PROMO", "GUIDE", "INFO", "OUI", "FIDELITE", "FIDEL",
    ],
    "sport_fitness": [
        "PROGRAMME", "BILAN", "GUIDE", "INFO", "OUI", "COACHING", "CLIENTS",
    ],
}


def _is_keyword_match(comment_text: str, niche: str) -> str | None:
    """Retourne le keyword matche (en majuscules) ou None."""
    text_upper = comment_text.upper()
    for kw in TRIGGER_KEYWORDS.get(niche, []):
        if kw in text_upper:
            return kw
    return None


async def _get_recent_videos_playwright(username: str, max_videos: int = 10) -> list[dict]:
    """Recupere les videos recentes d'un compte TikTok via Playwright."""
    videos = []

    try:
        from playwright_stealth import stealth_async

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--disable-setuid-sandbox", "--single-process",
                ],
            )
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
            await stealth_async(page)

            url = f"https://www.tiktok.com/@{username.lstrip('@')}"
            await page.goto(url, wait_until="networkidle", timeout=25000)
            await asyncio.sleep(2)

            video_data = await page.evaluate(
                """(maxVids) => {
                    const links = document.querySelectorAll('a[href*="/video/"]');
                    const seen = new Set();
                    const result = [];
                    for (const link of links) {
                        const href = link.href;
                        const match = href.match(/\\/video\\/(\\d+)/);
                        if (match && !seen.has(match[1])) {
                            seen.add(match[1]);
                            result.push({ video_id: match[1], url: href });
                        }
                        if (result.length >= maxVids) break;
                    }
                    return result;
                }""",
                max_videos,
            )

            videos = video_data or []
            await browser.close()

    except Exception as e:
        print(f"  Recuperation videos {username}: {e}")

    return videos


async def _get_comments_playwright(video_url: str, max_comments: int = 100) -> list[dict]:
    """Scrape les commentaires d'une video TikTok via Playwright."""
    comments = []

    try:
        from playwright_stealth import stealth_async

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--disable-setuid-sandbox", "--single-process",
                ],
            )
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
            await stealth_async(page)

            await page.goto(video_url, wait_until="networkidle", timeout=25000)
            await asyncio.sleep(3)

            for _ in range(3):
                await page.mouse.wheel(0, 800)
                await asyncio.sleep(1.5)

            raw_comments = await page.evaluate(
                """() => {
                    const items = document.querySelectorAll('[data-e2e="comment-level-1"]');
                    return Array.from(items).slice(0, 100).map(item => ({
                        username: item.querySelector('[data-e2e="comment-username-1"]')
                                    ?.textContent?.trim() || '',
                        comment: item.querySelector('[data-e2e="comment-text"]')
                                   ?.textContent?.trim() || '',
                        timestamp: item.querySelector('time')?.getAttribute('datetime') || '',
                    }));
                }"""
            )

            comments = [
                c for c in (raw_comments or [])
                if c.get("username") and c.get("comment")
            ]
            await browser.close()

    except Exception as e:
        print(f"  Scrape commentaires {video_url}: {e}")

    return comments


async def classify_comment_with_groq(comment: str, niche: str) -> dict:
    """Detecte l'intention d'achat dans un commentaire sans keyword exact."""
    if not GROQ_API_KEY:
        return {"is_interested": False, "confidence": 0.0, "keyword_equivalent": None}

    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)

    prompt = (
        f'Analyse ce commentaire TikTok dans la niche "{niche}" :\n'
        f'"{comment}"\n\n'
        "Est-ce que cette personne exprime un interet concret pour recevoir "
        "de l'aide / un guide / plus d'infos ?\n\n"
        "Reponds UNIQUEMENT en JSON strict :\n"
        '{"is_interested": true/false, "confidence": 0.0-1.0, "reason": "max 10 mots"}\n\n'
        "Exemples :\n"
        '- "c\'est quoi ?" -> {"is_interested": true, "confidence": 0.8, "reason": "demande d information"}\n'
        '- "je veux savoir" -> {"is_interested": true, "confidence": 0.9, "reason": "exprime desir explicite"}\n'
        '- "super" -> {"is_interested": false, "confidence": 0.1, "reason": "compliment sans intention"}\n'
        '- "comment tu fais ?" -> {"is_interested": true, "confidence": 0.85, "reason": "demande methode"}'
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.1,
        )
        import json

        result = json.loads(response.choices[0].message.content.strip())
        return result
    except Exception as e:
        print(f"  Groq classify: {e}")
        return {"is_interested": False, "confidence": 0.0, "keyword_equivalent": None}


async def scan_and_detect(
    account_username: str,
    niche: str,
    db,
    max_videos: int = 5,
) -> list[dict]:
    """Scanne les dernieres videos d'un compte TikTok.

    Retourne la liste des utilisateurs a qui envoyer un DM.
    Filtre les doublons via Firebase (DM deja envoye).
    """
    print(f"  Scan {account_username} ({niche})...")

    videos = await _get_recent_videos_playwright(account_username, max_videos=max_videos)

    if not videos:
        print(f"  Aucune video trouvee pour {account_username}")
        return []

    triggers = []
    already_processed = set()

    # Usernames deja DM-es pour cette niche
    existing_dms = db.collection("tiktok_dms").where("niche", "==", niche).stream()
    already_sent = {doc.to_dict().get("recipient_username") for doc in existing_dms}

    for video in videos:
        video_id = video.get("video_id")
        video_url = video.get("url")

        if not video_url:
            continue

        comments = await _get_comments_playwright(video_url, max_comments=100)

        # Commentaires deja traites en DB
        processed_in_db = set()
        stored = db.collection("tiktok_comments").where(
            "video_id", "==", video_id
        ).stream()
        for doc in stored:
            processed_in_db.add(doc.to_dict().get("comment_username"))

        # Couche 1 — Keywords exacts
        keyword_matches = []
        unmatched_comments = []

        for c in comments:
            username = c["username"]
            comment_text = c["comment"]

            if (
                username in already_sent
                or username in processed_in_db
                or username in already_processed
            ):
                continue

            keyword = _is_keyword_match(comment_text, niche)
            if keyword:
                keyword_matches.append({
                    "username": username,
                    "comment": comment_text,
                    "keyword": keyword,
                    "video_url": video_url,
                    "video_id": video_id,
                })
                already_processed.add(username)
            else:
                unmatched_comments.append(c)

        triggers.extend(keyword_matches)

        # Couche 2 — IA Groq (max 30 par video)
        if GROQ_API_KEY and unmatched_comments:
            for c in unmatched_comments[:30]:
                username = c["username"]
                if username in already_processed:
                    continue

                result = await classify_comment_with_groq(c["comment"], niche)

                if result.get("is_interested") and result.get("confidence", 0) >= 0.7:
                    triggers.append({
                        "username": username,
                        "comment": c["comment"],
                        "keyword": "AI_DETECTED",
                        "confidence": result.get("confidence"),
                        "video_url": video_url,
                        "video_id": video_id,
                    })
                    already_processed.add(username)

                db.collection("tiktok_comments").add({
                    "video_id": video_id,
                    "comment_username": username,
                    "comment_text": c["comment"],
                    "processed_at": datetime.now(timezone.utc),
                    "niche": niche,
                })

                await asyncio.sleep(0.1)

        # Sauvegarder les keyword matches aussi
        for m in keyword_matches:
            db.collection("tiktok_comments").add({
                "video_id": video_id,
                "comment_username": m["username"],
                "comment_text": m["comment"],
                "keyword": m["keyword"],
                "processed_at": datetime.now(timezone.utc),
                "niche": niche,
            })

        await asyncio.sleep(random.uniform(2, 4))

    print(f"  {account_username}: {len(triggers)} nouveaux triggers detectes")
    return triggers
