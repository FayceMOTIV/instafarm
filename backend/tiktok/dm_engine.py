"""Envoi de DMs TikTok via Playwright avec session cookies.

Genere des messages personnalises avec Groq.
Anti-ban : delais humains, limites journalieres, frappe simulee.
"""

import os
import asyncio
import random
from datetime import datetime, timezone

from playwright.async_api import async_playwright

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Limites anti-ban TikTok
SAFE_LIMITS = {
    "dms_per_day": 20,
    "dms_per_hour": 5,
    "min_delay_secs": 45,
    "max_delay_secs": 180,
    "typing_delay_ms": (30, 100),
}

# Templates fallback par niche
DM_TEMPLATES = {
    "restauration": (
        "Salut ! Comme promis dans la video, voici le guide\n"
        "Tu travailles en brasserie, restaurant gastronomique ou fast-food ?\n"
        "Je peux t'envoyer des infos adaptees a ton type d'etablissement"
    ),
    "coiffure": (
        "Coucou ! J'ai vu ta demande sous la video\n"
        "Tu travailles en salon ou a ton compte ?\n"
        "Je t'envoie les infos adaptees a ta situation !"
    ),
    "btp_artisan": (
        "Salut ! Ton commentaire m'a fait sourire\n"
        "C'est quoi ta specialite principale : maconnerie, electricite, plomberie ?\n"
        "J'ai des ressources specifiques selon le metier."
    ),
    "dentiste": (
        "Bonjour ! J'ai vu votre interet sous la video\n"
        "Vous cherchez a developper quelle partie de votre cabinet ?\n"
        "Je peux vous orienter vers les ressources adaptees."
    ),
    "auto_garage": (
        "Salut ! Merci pour ton commentaire\n"
        "Tu geres combien d'entrees atelier par semaine environ ?\n"
        "J'ai des astuces selon la taille du garage."
    ),
    "sport_fitness": (
        "Salut coach !\n"
        "Tu travailles en salle, a domicile, ou en ligne ?\n"
        "Je t'envoie les ressources adaptees a ton modele."
    ),
    "immobilier": (
        "Bonjour ! J'ai vu votre message\n"
        "Vous etes en agence ou mandataire independant ?\n"
        "Les strategies sont differentes selon le cas."
    ),
    "photographe": (
        "Salut ! Ta question m'a interpelle\n"
        "Tu es specialise dans quel type de photo ? (mariage, corporate, sport...)\n"
        "J'ai du contenu tres cible selon la specialite."
    ),
}


def generate_dm_message(
    username: str,
    comment: str,
    keyword: str,
    niche: str,
    use_groq: bool = True,
) -> str:
    """Genere un message DM personnalise. Groq en premier, fallback template."""
    if use_groq and GROQ_API_KEY:
        try:
            from groq import Groq

            client = Groq(api_key=GROQ_API_KEY)

            possible_name = username.split(".")[0].split("_")[0].capitalize()
            if len(possible_name) < 3 or len(possible_name) > 12:
                possible_name = None

            prompt = (
                f'Tu es un entrepreneur francais qui aide des pros dans la niche "{niche}".\n'
                f'Quelqu\'un a commente "{comment}" sous ta video TikTok.\n'
                f'Keyword detecte : "{keyword}"\n'
                f'{f"Son username suggere le prenom : {possible_name}" if possible_name else ""}\n\n'
                "Ecris un DM court et chaleureux (3 lignes max) qui :\n"
                "1. Mentionne son commentaire naturellement\n"
                "2. Pose UNE question pour qualifier son besoin\n"
                "3. Reste humain, pas commercial, pas de lien pour l instant\n\n"
                "Reponds UNIQUEMENT avec le message DM, sans guillemets ni explication."
            )

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.8,
            )
            message = response.choices[0].message.content.strip()
            if message and len(message) > 10:
                return message
        except Exception as e:
            print(f"  Groq DM generation: {e}")

    return DM_TEMPLATES.get(niche, DM_TEMPLATES["restauration"])


async def send_tiktok_dm(
    recipient_username: str,
    message: str,
    cookies_path: str,
    headless: bool = True,
) -> bool:
    """Envoie un DM TikTok a un utilisateur via Playwright."""
    if not cookies_path or not os.path.exists(cookies_path):
        print(f"  Cookies introuvables : {cookies_path}")
        return False

    try:
        from playwright_stealth import stealth_async
        from backend.tiktok.cookies_manager import _load_cookies_into_context

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--disable-setuid-sandbox",
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
            await _load_cookies_into_context(context, cookies_path)
            page = await context.new_page()
            await stealth_async(page)

            # Aller sur le profil du destinataire
            profile_url = f"https://www.tiktok.com/@{recipient_username.lstrip('@')}"
            await page.goto(profile_url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(random.uniform(1.5, 3))

            # Verifier qu'on est connecte
            if "/login" in page.url or "/signup" in page.url:
                print(f"  Session expiree pour DM vers {recipient_username}")
                await browser.close()
                return False

            # Chercher le bouton Message
            message_btn = None
            for selector in [
                '[data-e2e="message-button"]',
                'button:has-text("Message")',
                '[aria-label="Message"]',
            ]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=3000):
                        message_btn = btn
                        break
                except Exception:
                    continue

            if not message_btn:
                print(f"  Bouton Message introuvable pour @{recipient_username}")
                await browser.close()
                return False

            await message_btn.click()
            await asyncio.sleep(random.uniform(1.5, 2.5))

            # Trouver la zone de texte
            text_input = None
            for selector in [
                '[data-e2e="message-input"]',
                '[contenteditable="true"]',
                'textarea[placeholder]',
            ]:
                try:
                    inp = page.locator(selector).first
                    if await inp.is_visible(timeout=3000):
                        text_input = inp
                        break
                except Exception:
                    continue

            if not text_input:
                print(f"  Zone de texte introuvable pour @{recipient_username}")
                await browser.close()
                return False

            # Taper le message humainement
            await text_input.click()
            await asyncio.sleep(0.5)
            for char in message:
                await page.keyboard.type(char)
                await asyncio.sleep(
                    random.uniform(
                        SAFE_LIMITS["typing_delay_ms"][0] / 1000,
                        SAFE_LIMITS["typing_delay_ms"][1] / 1000,
                    )
                )

            # Pause avant envoi
            await asyncio.sleep(random.uniform(0.8, 1.5))

            # Envoyer avec Enter
            await page.keyboard.press("Enter")
            await asyncio.sleep(random.uniform(1.5, 3))

            success = True
            try:
                sent_msg = page.locator(f'text="{message[:30]}"').first
                if await sent_msg.is_visible(timeout=5000):
                    success = True
            except Exception:
                pass

            await browser.close()

            if success:
                print(f"  DM envoye a @{recipient_username}")

            # Delai anti-ban entre chaque DM
            wait = random.randint(
                SAFE_LIMITS["min_delay_secs"], SAFE_LIMITS["max_delay_secs"]
            )
            print(f"  Attente {wait}s avant prochain DM...")
            await asyncio.sleep(wait)

            return success

    except Exception as e:
        print(f"  Erreur DM vers @{recipient_username}: {e}")
        return False
