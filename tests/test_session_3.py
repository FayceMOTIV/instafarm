"""Tests Session 3 — Scraper + Scoring IA 3 couches."""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ajouter le dossier racine au path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Forcer un chemin DB de test
TEST_DB_PATH = ROOT_DIR / "instafarm_test_s3.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Cree la DB de test, seed tenant + niches, puis nettoie apres."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import Niche, Tenant

    async def _setup():
        await init_db()

        async with async_session() as session:
            tenant = Tenant(
                name="InstaFarm Solo Test",
                email="admin@instafarm.io",
                api_key="sk_test_warmachine_solo_2026",
                plan="war_machine",
                status="active",
                max_niches=10,
                max_accounts=30,
                max_dms_day=900,
            )
            session.add(tenant)
            await session.commit()

        from backend.seeds.seed_niches import NICHES

        async with async_session() as session:
            for niche_data in NICHES:
                niche = Niche(
                    tenant_id=1,
                    name=niche_data["name"],
                    emoji=niche_data["emoji"],
                    hashtags=json.dumps(niche_data["hashtags"], ensure_ascii=False),
                    target_account_count=niche_data["target_account_count"],
                    product_pitch=niche_data["product_pitch"],
                    dm_prompt_system=niche_data["dm_prompt_system"],
                    dm_fallback_templates=json.dumps(niche_data["dm_fallback_templates"], ensure_ascii=False),
                    scoring_vocab=json.dumps(niche_data["scoring_vocab"], ensure_ascii=False),
                )
                session.add(niche)
            await session.commit()

    asyncio.run(_setup())
    yield

    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def _get_niche_by_name(name: str):
    """Recupere une niche par son nom depuis la DB de test (sync helper)."""
    from backend.database import async_session
    from backend.models import Niche

    async def _fetch():
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(Niche).where(Niche.name == name, Niche.tenant_id == 1)
            )
            return result.scalar_one_or_none()

    return asyncio.run(_fetch())


# ===== TEST 1 : TF-IDF score restaurants =====
def test_tfidf_score_restaurants():
    """Bio avec 'restaurant', 'chef', 'cuisine' → score TF-IDF > 0.6 pour niche Restaurants."""
    from backend.bot.scorer import ProspectScorer

    niche = _get_niche_by_name("Restaurants")
    assert niche is not None, "Niche Restaurants non trouvee"

    scorer = ProspectScorer()
    profile = {
        "bio": "Chef cuisinier passionné 🍽️ Restaurant gastronomique à Lyon | Menu du jour | Réservations",
        "followers": 1500,
        "following": 300,
    }

    score = scorer._tfidf_score(profile, niche)
    print(f"\n[TF-IDF] Bio restaurant → score = {score:.4f}")
    assert score > 0.6, f"Score TF-IDF attendu > 0.6, obtenu {score:.4f}"


# ===== TEST 2 : TF-IDF wrong niche =====
def test_tfidf_score_wrong_niche():
    """Bio dentiste testee sur niche Restaurants → score < 0.2 → rejete."""
    from backend.bot.scorer import ProspectScorer

    niche = _get_niche_by_name("Restaurants")
    assert niche is not None

    scorer = ProspectScorer()
    profile = {
        "bio": "Chirurgien-dentiste | Implants dentaires et orthodontie | Cabinet moderne",
        "followers": 800,
        "following": 200,
    }

    score = scorer._tfidf_score(profile, niche)
    print(f"\n[TF-IDF] Bio dentiste sur niche Restaurants → score = {score:.4f}")
    assert score < 0.2, f"Score TF-IDF attendu < 0.2, obtenu {score:.4f}"


# ===== TEST 3 : Groq scoring (vraie call si GROQ_API_KEY present) =====
def test_groq_score_real_call():
    """
    Vraie call Groq avec une bio restaurant fictive.
    Verifie que la reponse est un float entre 0 et 1.
    MONTRE la reponse Groq dans le terminal.
    """
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        pytest.skip("GROQ_API_KEY non defini, skip test Groq reel")

    from backend.services.groq_service import score_bio_with_groq

    async def _test():
        bio = "Restaurant italien La Bella Vita | Pizzas artisanales & pâtes fraîches | Lyon 6ème | Réservations"
        score = await score_bio_with_groq(bio, "Restaurants", "AppySolution : app mobile de commande et fidélité pour restaurants")
        print(f"\n[GROQ] Bio restaurant → score Groq = {score:.4f}")
        assert 0.0 <= score <= 1.0, f"Score Groq hors bornes: {score}"
        assert score > 0.3, f"Score Groq trop bas pour un vrai restaurant: {score}"
        return score

    asyncio.run(_test())


# ===== TEST 4 : Intent score compte actif =====
def test_intent_score_active_account():
    """Compte avec post recent + link in bio + bon ratio → intent_score > 0.5."""
    from backend.bot.scorer import ProspectScorer

    scorer = ProspectScorer()
    profile = {
        "followers": 2000,
        "following": 500,
        "has_link_in_bio": True,
        "account_age_days": 400,      # < 2 ans
        "last_post_days": 2,          # actif !
        "engagement_rate": 4.5,       # > 3%
        "follower_growth": 8.0,       # > 5%/mois
    }

    score = scorer._intent_score(profile)
    print(f"\n[INTENT] Compte actif → intent_score = {score:.4f}")
    assert score > 0.5, f"Intent score attendu > 0.5, obtenu {score:.4f}"


# ===== TEST 5 : Intent score compte mort =====
def test_intent_score_dead_account():
    """Compte avec dernier post 90j + mauvais ratio → intent_score < 0.2."""
    from backend.bot.scorer import ProspectScorer

    scorer = ProspectScorer()
    profile = {
        "followers": 100,
        "following": 5000,             # ratio suspect (50x)
        "has_link_in_bio": False,
        "account_age_days": 1500,      # > 2 ans
        "last_post_days": 90,          # > 60 jours → inactif
        "engagement_rate": 0.5,
        "follower_growth": 0.0,
    }

    score = scorer._intent_score(profile)
    print(f"\n[INTENT] Compte mort → intent_score = {score:.4f}")
    assert score < 0.2, f"Intent score attendu < 0.2, obtenu {score:.4f}"


# ===== TEST 6 : Deduplication =====
def test_deduplication():
    """
    Insere prospect en DB.
    Essaie de le scraper a nouveau.
    Verifie qu'il est filtre par _deduplicate_global().
    """
    from backend.bot.scraper import InstagramScraper
    from backend.database import async_session
    from backend.models import Prospect

    async def _test():
        # Inserer un prospect existant
        async with async_session() as session:
            prospect = Prospect(
                tenant_id=1,
                niche_id=1,
                instagram_id="99999999",
                username="existing_restaurant",
                bio="Deja en base",
                followers=500,
                following=200,
                posts_count=50,
                status="scored",
            )
            session.add(prospect)
            await session.commit()

        # Tester la deduplication
        scraper = InstagramScraper(apify_token="fake")
        profiles = [
            {"instagram_id": "99999999", "username": "existing_restaurant"},
            {"instagram_id": "11111111", "username": "new_restaurant"},
        ]

        filtered = await scraper._deduplicate_global(profiles, tenant_id=1)
        print(f"\n[DEDUP] 2 profils en entree, {len(filtered)} apres dedup")

        assert len(filtered) == 1, f"Attendu 1 profil apres dedup, obtenu {len(filtered)}"
        assert filtered[0]["instagram_id"] == "11111111"

    asyncio.run(_test())


# ===== TEST 7 : City extraction =====
def test_city_extraction():
    """
    Bio 'Restaurant Italien | Lyon 69 | Réservations...' → city == 'Lyon'
    Bio sans ville → city == None
    """
    from backend.bot.scraper import extract_city

    # Cas 1 : ville presente
    bio1 = "🍕 Restaurant Italien | Lyon 69 | Réservations au 04.72.xxx"
    city1 = extract_city(bio1)
    print(f"\n[GEO] Bio '{bio1[:40]}...' → city = {city1}")
    assert city1 == "Lyon", f"Attendu 'Lyon', obtenu '{city1}'"

    # Cas 2 : pas de ville
    bio2 = "Passionné de cuisine depuis toujours 🍽️ Livraison partout"
    city2 = extract_city(bio2)
    print(f"[GEO] Bio '{bio2[:40]}...' → city = {city2}")
    assert city2 is None, f"Attendu None, obtenu '{city2}'"

    # Cas 3 : Paris
    bio3 = "Cabinet dentaire Paris 16ème | Dr Martin"
    city3 = extract_city(bio3)
    print(f"[GEO] Bio '{bio3[:40]}...' → city = {city3}")
    assert city3 == "Paris", f"Attendu 'Paris', obtenu '{city3}'"

    # Cas 4 : Aix-en-Provence
    bio4 = "Garage automobile Aix-en-Provence | Toutes marques"
    city4 = extract_city(bio4)
    print(f"[GEO] Bio '{bio4[:40]}...' → city = {city4}")
    assert city4 == "Aix-en-Provence", f"Attendu 'Aix-en-Provence', obtenu '{city4}'"


# ===== TEST 8 : Full pipeline mock =====
def test_full_pipeline_mock():
    """
    Mock Apify pour retourner 10 profils fictifs.
    Verifie que le pipeline complet tourne sans erreur.
    Verifie que les prospects sont sauves en DB avec status='scored'.
    MONTRE le log final : X scraped, Y scored, Z rejetes.
    """
    from backend.bot.scorer import ProspectScorer, ingest_prospects_for_niche
    from backend.bot.scraper import InstagramScraper

    niche = _get_niche_by_name("Restaurants")
    assert niche is not None

    # 10 profils fictifs : 5 bons restaurants + 5 mauvais (hors niche)
    mock_profiles = [
        # 5 bons restaurants (score devrait etre >= 0.5)
        {
            "instagram_id": f"good_{i}",
            "username": f"restaurant_bon_{i}",
            "full_name": f"Restaurant Bon {i}",
            "bio": "Restaurant gastronomique | Chef cuisinier | Menu carte cuisine française | Réservations Lyon",
            "followers": 2000,
            "following": 400,
            "posts_count": 100,
            "has_link_in_bio": True,
            "profile_pic_url": "",
            "is_private": False,
            "account_age_days": 300,
            "last_post_days": 3,
            "engagement_rate": 4.0,
            "follower_growth": 6.0,
        }
        for i in range(5)
    ] + [
        # 5 mauvais (bio hors-sujet)
        {
            "instagram_id": f"bad_{i}",
            "username": f"random_compte_{i}",
            "full_name": f"Random {i}",
            "bio": "Voyage backpack digital nomad crypto blockchain NFT",
            "followers": 500,
            "following": 300,
            "posts_count": 20,
            "has_link_in_bio": False,
            "profile_pic_url": "",
            "is_private": False,
            "account_age_days": 1000,
            "last_post_days": 45,
            "engagement_rate": 1.0,
            "follower_growth": 0.5,
        }
        for i in range(5)
    ]

    async def _test():
        # Mock le scraper pour retourner nos profils
        mock_scraper = InstagramScraper(apify_token="fake")
        mock_scraper.scrape_niche = AsyncMock(return_value=mock_profiles)

        # Mock Groq pour scorer sans API key
        mock_scorer = ProspectScorer()

        async def fake_groq_score(profile, niche):
            bio = profile.get("bio", "")
            if "restaurant" in bio.lower() or "chef" in bio.lower() or "cuisine" in bio.lower():
                return 0.8
            return 0.2

        mock_scorer._groq_score = fake_groq_score

        result = await ingest_prospects_for_niche(
            niche=niche,
            tenant_id=1,
            scraper=mock_scraper,
            scorer=mock_scorer,
            limit=100,
        )

        print(f"\n[PIPELINE] Resultat: {result}")
        print(f"  → {result['scraped']} scraped, {result['scored']} scored, {result['rejected']} rejetes")

        assert result["scraped"] == 10, f"Attendu 10 scraped, obtenu {result['scraped']}"
        assert result["scored"] >= 4, f"Attendu >= 4 scored (bons restaurants), obtenu {result['scored']}"
        assert result["rejected"] >= 4, f"Attendu >= 4 rejetes (hors-niche), obtenu {result['rejected']}"

        # Verifier en DB que les prospects sont bien sauves
        from sqlalchemy import select, func
        from backend.database import async_session
        from backend.models import Prospect

        async with async_session() as session:
            count_result = await session.execute(
                select(func.count(Prospect.id)).where(
                    Prospect.tenant_id == 1,
                    Prospect.status == "scored",
                    Prospect.username.like("restaurant_bon_%"),
                )
            )
            count = count_result.scalar()

        print(f"  → {count} prospects 'scored' sauves en DB")
        assert count >= 4, f"Attendu >= 4 prospects scored en DB, obtenu {count}"

    asyncio.run(_test())
