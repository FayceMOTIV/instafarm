"""
BioManager — Bios Instagram adaptees par niche.

Chaque compte du pool recoit une bio coherente avec la niche
qu'il cible, pour paraitre naturel.
"""

import asyncio
import json
import logging
import random
from datetime import datetime

from sqlalchemy import select

from backend.database import async_session
from backend.models import IgAccount

logger = logging.getLogger("instafarm.bio")

BIOS_PAR_NICHE: dict[str, list[str]] = {
    "restaurant": [
        "Passionnee de gastronomie | Je decouvre les meilleures tables de France",
        "Food lover | A la recherche des pepites culinaires cachees",
        "Cuisiniere amateur | J'adore partager mes bonnes adresses resto",
    ],
    "dentiste": [
        "Hygiene dentaire au quotidien | Conseils sante bucco-dentaire",
        "Passionnee de bien-etre | Le sourire est ma priorite",
        "Sante & bien-etre | Je partage mes conseils quotidiens",
    ],
    "coiffeur": [
        "Passionnee de coiffure | Toujours a l'affut des nouvelles tendances",
        "Hair lover | J'adore me transformer et tester de nouveaux looks",
        "Beaute & style | Mes inspirations coiffure du moment",
    ],
    "garagiste": [
        "Passionnee d'automobile | Mon garage, mon terrain de jeu",
        "Road trip lover | Je documente mes aventures mecaniques",
        "Auto enthusiast | Conseils entretien et bonnes adresses",
    ],
    "pharmacie": [
        "Bien-etre au naturel | Mes astuces sante du quotidien",
        "Passionnee de parapharmacie | Tests et avis produits",
        "Sante naturelle | Je partage mes decouvertes bien-etre",
    ],
    "avocat": [
        "Passionnee de droit | Je vulgarise les sujets juridiques du quotidien",
        "Citoyenne engagee | Comprendre ses droits c'est essentiel",
        "Culture juridique | Mes lectures et decouvertes du moment",
    ],
    "architecte": [
        "Passionnee d'architecture | Je visite et documente des lieux uniques",
        "Design & deco d'interieur | Mes inspirations du moment",
        "Amoureuse du beau | Architecture, art et patrimoine",
    ],
    "veterinaire": [
        "Maman de 2 chats | Conseils bien-etre animal",
        "Animal lover | Je partage les meilleures adresses pour nos compagnons",
        "Passionnee d'animaux | Soins, alimentation et bonheur de nos boules de poils",
    ],
    "opticien": [
        "Passionnee de lunettes | Chaque monture raconte une histoire",
        "Style & vision | Mes coups de coeur optiques du moment",
        "Fashion eyes | Je teste les dernieres tendances lunettes",
    ],
    "notaire": [
        "Projet immobilier en cours | Je documente mon parcours d'acheteuse",
        "Passionnee d'immobilier | Conseils et retours d'experience",
        "Futur proprio | Mon aventure d'achat pas a pas",
    ],
    "boulangerie": [
        "Amoureuse de boulangerie artisanale | A la recherche du meilleur croissant",
        "Pain & viennoiseries | Je teste les boulangeries de ma ville",
        "Patissiere amateur | Mes decouvertes sucrees du moment",
    ],
    "beaute": [
        "Beauty addict | Nail art, soins & tendances beaute",
        "Passionnee d'esthetique | Je teste pour vous les meilleurs instituts",
        "Self-care lover | Prendre soin de soi c'est essentiel",
    ],
    "btp": [
        "Passionnee de renovation | Je suis ma maison pas a pas",
        "En plein chantier ! | Je documente ma reno maison",
        "Architecture & deco | Mes projets de construction en cours",
    ],
    "immobilier": [
        "En recherche du bien parfait | Mon parcours acheteur",
        "Investisseur immobilier debutant | J'apprends et je partage",
        "Passionnee d'immobilier | Visite de biens & conseils",
    ],
    "sport": [
        "Fitness addict | Ma routine sport au quotidien",
        "Yoga & bien-etre | Je partage mon chemin vers la forme",
        "Coaching perso | Objectif : rester motivee toute l'annee",
    ],
}

# Fallback generique
DEFAULT_BIOS = [
    "Curieuse de nature | J'adore decouvrir de nouvelles choses",
    "Passionnee de vie | Toujours a la recherche de belles rencontres",
    "Exploratrice | Je partage mes decouvertes du quotidien",
]


def get_bio_for_niche(niche: str) -> str:
    """Retourne une bio aleatoire pour la niche."""
    niche_key = niche.lower().rstrip("s")
    bios = BIOS_PAR_NICHE.get(niche_key, DEFAULT_BIOS)
    return random.choice(bios)


async def update_bio_for_niche(account_id: int, niche: str) -> bool:
    """
    Change la bio du compte pour correspondre a la niche cible.
    Utilise Playwright pour modifier le profil Instagram.

    Args:
        account_id: ID du compte IgAccount
        niche: nom de la niche (ex: "restaurant")

    Returns:
        True si bio mise a jour
    """
    from backend.accounts.playwright_login import login_from_session

    # Charger le compte
    async with async_session() as session:
        result = await session.execute(
            select(IgAccount).where(IgAccount.id == account_id)
        )
        account = result.scalars().first()
        if not account:
            return False

    new_bio = get_bio_for_niche(niche)

    # Skip si deja la bonne niche avec une bio
    if account.current_niche == niche and account.current_bio:
        logger.info(f"[Bio] @{account.username} deja configure pour '{niche}'")
        return True

    # Login depuis session
    pw, browser, context, page = await login_from_session(account_id)
    if not page:
        logger.error(f"[Bio] @{account.username} login echoue")
        return False

    success = False
    try:
        # Aller sur la page edit profil
        await page.goto(
            "https://www.instagram.com/accounts/edit/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await asyncio.sleep(4)

        # Trouver le champ bio — sur le web c'est un textarea
        bio_field = page.locator("textarea").first
        if await bio_field.count() > 0 and await bio_field.is_visible(timeout=5000):
            await bio_field.click()
            await asyncio.sleep(0.3)
            # Triple-click pour tout selectionner
            await bio_field.click(click_count=3)
            await asyncio.sleep(0.3)
            await bio_field.fill(new_bio)
            await asyncio.sleep(1)

            # Sauvegarder — le bouton est un div[role="button"] ou button
            for btn_text in ["Envoyer", "Submit", "Soumettre"]:
                try:
                    submit = page.get_by_role("button", name=btn_text)
                    if await submit.is_visible(timeout=2000):
                        await submit.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        await submit.click()
                        await asyncio.sleep(3)
                        success = True
                        break
                except Exception:
                    continue
        else:
            logger.warning("[Bio] Textarea bio non trouvee sur /accounts/edit/")

        if success:
            # Sauvegarder en DB
            async with async_session() as session:
                result = await session.execute(
                    select(IgAccount).where(IgAccount.id == account_id)
                )
                acc = result.scalars().first()
                if acc:
                    acc.current_bio = new_bio
                    acc.current_niche = niche
                    acc.bio_updated_at = datetime.utcnow()
                    await session.commit()

            logger.info(f"[Bio] @{account.username} bio mise a jour pour '{niche}'")
        else:
            logger.warning(f"[Bio] @{account.username} echec mise a jour bio")

    except Exception as e:
        logger.error(f"[Bio] @{account.username} erreur: {e}")

    finally:
        await browser.close()
        await pw.stop()

    return success
