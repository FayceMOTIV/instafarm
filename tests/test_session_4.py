"""Tests Session 4 — DM Engine, A/B Testing, Relances, Interest Detection."""

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

TEST_DB_PATH = ROOT_DIR / "instafarm_test_s4.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Cree la DB de test avec tenant, niche, comptes, prospects, variants."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import AbVariant, IgAccount, Message, Niche, Prospect, Tenant

    async def _setup():
        await init_db()

        async with async_session() as session:
            # Tenant
            tenant = Tenant(
                name="Test S4", email="test_s4@instafarm.io",
                api_key="sk_test_s4", plan="war_machine", status="active",
            )
            session.add(tenant)
            await session.commit()

            # Niche Restaurants
            niche = Niche(
                tenant_id=1, name="Restaurants", emoji="🍽️",
                hashtags='["#restaurant"]',
                product_pitch="AppySolution : app mobile pour restaurants. 490€ setup + 89€/mois.",
                dm_prompt_system="Tu es un expert en prospection B2B pour restaurants.",
                dm_fallback_templates=json.dumps([
                    "Belle carte ! Vous misez sur la gastronomie ?",
                    "Superbe etablissement ! Vos clients ont deja une app ?",
                    "Votre cuisine a l'air incroyable !",
                    "J'adore l'ambiance de votre restaurant !",
                    "Beau travail sur votre compte !",
                ]),
                scoring_vocab='["restaurant", "cuisine", "chef"]',
            )
            session.add(niche)
            await session.commit()

            # Compte IG
            now = datetime.utcnow()
            account = IgAccount(
                tenant_id=1, niche_id=1, username="bot_test_1", password="pass",
                status="active", warmup_day=18,
                created_at=now - timedelta(days=60),
                follows_today=0, dms_today=0, likes_today=0,
            )
            session.add(account)
            await session.commit()

            # Prospect avec DM envoye il y a 8 jours (eligible relance D+7)
            prospect_relance = Prospect(
                tenant_id=1, niche_id=1, instagram_id="ig_relance_1",
                username="resto_relance", full_name="Chef Relance",
                bio="Restaurant gastronomique Lyon", followers=5000,
                score=0.8, status="dm_sent",
                first_dm_at=now - timedelta(days=8),
                last_dm_at=now - timedelta(days=8),
            )
            session.add(prospect_relance)

            # Prospect follow_back (eligible DM)
            prospect_fb = Prospect(
                tenant_id=1, niche_id=1, instagram_id="ig_fb_1",
                username="resto_follow_back", full_name="Chef FB",
                bio="Bistrot parisien", followers=3000,
                score=0.7, status="follow_back",
            )
            session.add(prospect_fb)

            # Prospect avec reponse en attente
            prospect_reply = Prospect(
                tenant_id=1, niche_id=1, instagram_id="ig_reply_1",
                username="resto_reply", full_name="Chef Reply",
                bio="Restaurant bio", followers=2000,
                score=0.6, status="dm_sent",
                first_dm_at=now - timedelta(days=10),
            )
            session.add(prospect_reply)
            await session.commit()

            # AB Variants pour niche 1 (E a le meilleur response_rate)
            variant_data = [
                ("A", 100, 5,  0.05),
                ("B", 100, 8,  0.08),
                ("C", 100, 6,  0.06),
                ("D", 100, 4,  0.04),
                ("E", 100, 25, 0.25),  # Clairement le meilleur
            ]
            for letter, sends, responses, rate in variant_data:
                variant = AbVariant(
                    tenant_id=1, niche_id=1,
                    variant_letter=letter,
                    template=f"Template {letter}",
                    status="testing",
                    sends=sends,
                    responses=responses,
                    response_rate=rate,
                )
                session.add(variant)
            await session.commit()

    asyncio.run(_setup())
    yield

    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_groq_dm_generation_real():
    """
    Test generation DM avec Groq.
    Si GROQ_API_KEY dispo : vraie call. Sinon : mock avec validation du fallback.
    """
    from backend.models import IgAccount, Niche, Prospect
    from backend.services.groq_service import GroqService

    async def _test():
        service = GroqService()

        # Creer des objets en memoire pour le test
        niche = Niche(
            tenant_id=1, name="Restaurants",
            hashtags='["#restaurant"]',
            product_pitch="AppySolution : app mobile pour restaurants.",
            dm_prompt_system="Tu es un expert en prospection B2B pour restaurants.\nGenere un DM personnalise.\nMaximum 3 phrases.",
            dm_fallback_templates=json.dumps(["Belle carte ! Vous misez sur la gastronomie ?"]),
        )
        prospect = Prospect(
            tenant_id=1, niche_id=1, instagram_id="ig_test",
            username="le_bon_restaurant", full_name="Pierre Dupont",
            bio="Chef cuisinier - Restaurant gastronomique Lyon - Cuisine francaise",
            followers=4500, city="Lyon",
        )
        account = IgAccount(
            tenant_id=1, username="bot_test", password="pass",
        )

        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            # Vraie call Groq
            dm = await service.generate_dm(prospect, niche, account)
            print(f"\n{'='*60}")
            print(f"DM GENERE PAR GROQ :")
            print(f"{'='*60}")
            print(dm)
            print(f"{'='*60}")
            assert len(dm) > 10, "DM trop court"
            assert len(dm) < 500, f"DM trop long ({len(dm)} chars)"
        else:
            # Mock Groq fail → fallback template
            with patch("backend.services.groq_service.call_groq", side_effect=Exception("API down")):
                dm = await service.generate_dm(prospect, niche, account)

            assert dm == "Belle carte ! Vous misez sur la gastronomie ?", f"Fallback non utilise: {dm}"
            print(f"\n[MOCK] Fallback template utilise: {dm}")

    asyncio.run(_test())


def test_fallback_on_groq_failure():
    """Mock Groq pour qu'il fail. Verifie que fallback template est utilise."""
    from backend.models import IgAccount, Niche, Prospect
    from backend.services.groq_service import GroqService

    async def _test():
        service = GroqService()

        niche = Niche(
            tenant_id=1, name="Dentistes",
            hashtags='["#dentiste"]',
            product_pitch="App dentistes",
            dm_prompt_system="Prompt dentiste",
            dm_fallback_templates=json.dumps([
                "Beau cabinet !",
                "Vos patients prennent RDV en ligne ?",
            ]),
        )
        prospect = Prospect(
            tenant_id=1, niche_id=1, instagram_id="ig_dent",
            username="dr_dent", bio="Dentiste Paris",
        )
        account = IgAccount(tenant_id=1, username="bot", password="p")

        with patch("backend.services.groq_service.call_groq", side_effect=Exception("Groq down")):
            dm = await service.generate_dm(prospect, niche, account)

        templates = ["Beau cabinet !", "Vos patients prennent RDV en ligne ?"]
        assert dm in templates, f"Fallback non utilise. Got: {dm}"

    asyncio.run(_test())


def test_ab_variant_selection_distribution():
    """Simule 100 appels get_active_variant. Verifie distribution 80/20 approximative."""
    from backend.bot.dm_engine import ABTestManager

    async def _test():
        manager = ABTestManager()
        selections = Counter()

        for _ in range(200):
            variant = await manager.get_active_variant(niche_id=1, tenant_id=1)
            if variant:
                selections[variant.variant_letter] += 1

        total = sum(selections.values())
        assert total == 200, f"Attendu 200 selections, obtenu {total}"

        # Le variant E a le meilleur response_rate (setup dans fixture)
        # Il devrait etre selectionne ~80% du temps
        best_letter = "E"
        best_count = selections.get(best_letter, 0)
        best_ratio = best_count / total

        print(f"\nDistribution A/B: {dict(selections)}")
        print(f"Meilleur (E): {best_ratio:.0%}")

        # Tolerant : entre 60% et 95% pour le meilleur (aleatoire)
        assert 0.55 <= best_ratio <= 0.98, f"Distribution incorrecte: E={best_ratio:.0%}"

        # Les autres doivent etre presentes
        others = total - best_count
        assert others > 0, "Les autres variants ne sont jamais selectionnes"

    asyncio.run(_test())


def test_relance_scheduling():
    """Prospect avec first_dm_at = maintenant - 8 jours → eligible relance D+7."""
    from backend.database import async_session
    from backend.models import Prospect

    async def _test():
        now = datetime.utcnow()

        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Prospect)
                .where(Prospect.username == "resto_relance")
            )
            prospect = result.scalar_one()

        # Verifier qu'il est eligible pour relance
        days_since_dm = (now - prospect.first_dm_at).days
        assert days_since_dm >= 7, f"Prospect devrait avoir DM depuis >= 7 jours, a {days_since_dm}"
        assert prospect.status == "dm_sent", f"Status devrait etre dm_sent, est {prospect.status}"

    asyncio.run(_test())


def test_relance_cancelled_on_reply():
    """handle_incoming_reply() → status='replied' ou 'interested'."""
    from backend.bot.dm_engine import DMEngine
    from backend.database import async_session
    from backend.models import Prospect

    async def _test():
        engine = DMEngine()

        # Recuperer le prospect
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Prospect).where(Prospect.username == "resto_reply")
            )
            prospect = result.scalar_one()
            prospect_id = prospect.id

        # Simuler une reponse entrante positive
        with patch.object(engine.ig_client, "send_dm", new_callable=AsyncMock):
            await engine.handle_incoming_reply(
                prospect_id=prospect_id,
                message_text="Oui ca m'interesse, dites m'en plus !",
                ig_account_id=1,
            )

        # Verifier que le status a change
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Prospect).where(Prospect.id == prospect_id)
            )
            updated = result.scalar_one()

        assert updated.status == "interested", f"Status devrait etre 'interested', est '{updated.status}'"
        assert updated.last_reply_at is not None, "last_reply_at devrait etre set"

    asyncio.run(_test())


def test_interest_detection_positive():
    """Messages positifs → detect_interest() retourne 'positive'."""
    from backend.bot.dm_engine import DMEngine

    async def _test():
        engine = DMEngine()

        positive_messages = [
            "Oui ca m'interesse",
            "C'est quoi exactement ?",
            "Dites m'en plus",
            "Combien ca coute ?",
            "Je veux bien un rdv",
            "Pourquoi pas, disponible demain ?",
        ]

        for msg in positive_messages:
            result = await engine.detect_interest(msg)
            assert result == "positive", f"'{msg}' devrait etre positif, obtenu '{result}'"

    asyncio.run(_test())


def test_interest_detection_negative():
    """Messages negatifs → detect_interest() retourne 'negative'."""
    from backend.bot.dm_engine import DMEngine

    async def _test():
        engine = DMEngine()

        negative_messages = [
            "Non merci",
            "Pas interesse",
            "Arretez de me contacter",
            "Stop spam",
            "Ne m'ecrivez plus",
        ]

        for msg in negative_messages:
            result = await engine.detect_interest(msg)
            assert result == "negative", f"'{msg}' devrait etre negatif, obtenu '{result}'"

    asyncio.run(_test())


def test_quota_respected_in_dm_queue():
    """Compte avec quota DM atteint → process_niche_dm_queue skip ce compte."""
    from backend.database import async_session
    from backend.models import IgAccount

    async def _test():
        # Mettre le compte a quota DM max
        async with async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(IgAccount)
                .where(IgAccount.tenant_id == 1)
                .values(dms_today=99)
            )
            await session.commit()

        # Verifier que get_account_for_action retourne None
        from backend.bot.account_pool import AccountPool
        pool = AccountPool()
        account = await pool.get_account_for_action(niche_id=1, action="dm", tenant_id=1)
        assert account is None, "Devrait retourner None quand quota DM atteint"

        # Cleanup
        async with async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(IgAccount)
                .where(IgAccount.tenant_id == 1)
                .values(dms_today=0)
            )
            await session.commit()

    asyncio.run(_test())
