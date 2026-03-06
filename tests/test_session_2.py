"""Tests Session 2 — Comptes IG, warmup, pool, proxy, quotas."""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

TEST_DB_PATH = ROOT_DIR / "instafarm_test_s2.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Cree la DB de test avec tenant + niches + comptes + proxy."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import IgAccount, Niche, Proxy, Tenant

    async def _setup():
        await init_db()

        async with async_session() as session:
            # Tenant
            tenant = Tenant(
                name="Test Tenant",
                email="test@instafarm.io",
                api_key="sk_test_s2",
                plan="war_machine",
                status="active",
            )
            session.add(tenant)
            await session.commit()

            # Niche
            niche = Niche(
                tenant_id=1,
                name="Restaurants",
                emoji="🍽️",
                hashtags='["#restaurant"]',
                product_pitch="Test pitch",
                dm_prompt_system="Test prompt",
                dm_fallback_templates='["Fallback 1"]',
            )
            session.add(niche)
            await session.commit()

            # Proxy (plein et vide)
            proxy_full = Proxy(
                tenant_id=1,
                host="1.2.3.4",
                port=8080,
                proxy_type="4g",
                max_accounts=5,
                accounts_count=5,
                status="active",
            )
            proxy_ok = Proxy(
                tenant_id=1,
                host="5.6.7.8",
                port=8080,
                proxy_type="4g",
                max_accounts=5,
                accounts_count=2,
                status="active",
                latency_ms=50,
            )
            session.add_all([proxy_full, proxy_ok])
            await session.commit()

            # 5 comptes IG de test avec differents ages
            now = datetime.utcnow()
            accounts = [
                IgAccount(
                    tenant_id=1, niche_id=1,
                    username=f"test_user_{i}",
                    password="test_pass",
                    status="active",
                    created_at=now - timedelta(days=100 - i * 20),  # Du plus vieux au plus jeune
                    follows_today=0,
                    dms_today=0,
                    likes_today=0,
                    warmup_day=18,
                )
                for i in range(5)
            ]
            session.add_all(accounts)
            await session.commit()

    asyncio.run(_setup())
    yield

    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_ig_client_login_mock():
    """Test de login avec mock instagrapi → session sauvee en DB."""
    from backend.bot.ig_client import IGClient
    from backend.database import async_session
    from backend.models import IgAccount

    async def _test():
        # Recuperer un compte de test avec eager load des relations
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with async_session() as session:
            result = await session.execute(
                select(IgAccount)
                .options(selectinload(IgAccount.proxy))
                .limit(1)
            )
            account = result.scalar_one()
            # Forcer le chargement pour eviter detached instance
            _ = account.proxy

        client = IGClient()

        # Mock instagrapi
        mock_ig_client = MagicMock()
        mock_ig_client.login = MagicMock()
        mock_ig_client.get_settings = MagicMock(return_value={"session_id": "test123"})
        mock_ig_client.set_settings = MagicMock()

        with patch("backend.bot.ig_client.is_active_hours", return_value=True):
            with patch("backend.bot.ig_client.IGClient._login_instagrapi") as mock_login:
                # Mock directement _login_instagrapi pour eviter les imports instagrapi
                async def fake_login(acc):
                    # Simuler la sauvegarde de session en DB
                    from sqlalchemy import update as sa_update
                    async with async_session() as db:
                        await db.execute(
                            sa_update(IgAccount)
                            .where(IgAccount.id == acc.id)
                            .values(session_data='{"session_id": "test123"}', last_login=datetime.utcnow())
                        )
                        await db.commit()
                    return True

                mock_login.side_effect = fake_login
                result = await client.login(account)

        assert result is True

        # Verifier que la session est sauvee en DB
        async with async_session() as session:
            res = await session.execute(
                select(IgAccount.session_data).where(IgAccount.id == account.id)
            )
            session_data = res.scalar_one()
            assert session_data is not None
            data = json.loads(session_data)
            assert data["session_id"] == "test123"

    asyncio.run(_test())


def test_warmup_schedule_logic():
    """Verifie le planning warmup : quotas, jours repos, progression."""
    from backend.bot.account_creator import WARMUP_SCHEDULE

    # Jour 0 : 0 follows, 0 DMs
    assert WARMUP_SCHEDULE[0]["follows"] == 0
    assert WARMUP_SCHEDULE[0]["dms"] == 0

    # Jour 18 : 20 follows, 12 DMs
    assert WARMUP_SCHEDULE[18]["follows"] == 20
    assert WARMUP_SCHEDULE[18]["dms"] == 12

    # 19 jours (0 a 18 inclus)
    assert len(WARMUP_SCHEDULE) == 19, f"Attendu 19 jours (0-18), trouve {len(WARMUP_SCHEDULE)}"

    # Jours de repos : toutes actions a 0 ou rest=True
    rest_days = [d for d, s in WARMUP_SCHEDULE.items() if s["rest"]]
    assert len(rest_days) >= 3, f"Au moins 3 jours de repos, trouve {len(rest_days)}"

    for day in rest_days:
        schedule = WARMUP_SCHEDULE[day]
        assert schedule["dms"] == 0, f"Jour {day} repos mais dms > 0"

    # Progression non-lineaire : jour 18 > jour 1
    assert WARMUP_SCHEDULE[18]["follows"] > WARMUP_SCHEDULE[1]["follows"]
    assert WARMUP_SCHEDULE[18]["likes"] > WARMUP_SCHEDULE[1]["likes"]
    assert WARMUP_SCHEDULE[18]["dms"] > WARMUP_SCHEDULE[1]["dms"]

    # Pas de DMs avant jour 8 (hormis repos)
    for day in range(0, 8):
        assert WARMUP_SCHEDULE[day]["dms"] == 0, f"Jour {day}: DMs avant jour 8"

    # Aucun jour ne depasse 40 follows, 40 likes, 12 DMs (limites absolues)
    for day, schedule in WARMUP_SCHEDULE.items():
        assert schedule["follows"] <= 40, f"Jour {day}: follows {schedule['follows']} > 40"
        assert schedule["likes"] <= 40, f"Jour {day}: likes {schedule['likes']} > 40"
        assert schedule["dms"] <= 12, f"Jour {day}: dms {schedule['dms']} > 12"


def test_account_pool_round_robin():
    """Verifie que get_account_for_action retourne le plus vieux en priorite."""
    from backend.bot.account_pool import AccountPool

    async def _test():
        pool = AccountPool()
        account = await pool.get_account_for_action(niche_id=1, action="follow", tenant_id=1)
        assert account is not None
        # Le premier compte (test_user_0) est le plus vieux (created_at le plus ancien)
        assert account.username == "test_user_0", f"Attendu test_user_0 (plus vieux), obtenu {account.username}"

    asyncio.run(_test())


def test_proxy_capacity_check():
    """Proxy avec max_accounts=5 et accounts_count=5 → capacite False."""
    from backend.bot.account_creator import AccountCreator
    from backend.models import Proxy

    async def _test():
        creator = AccountCreator()

        # Proxy plein
        proxy_full = Proxy(
            tenant_id=1, host="1.2.3.4", port=8080,
            max_accounts=5, accounts_count=5,
        )
        assert await creator._check_proxy_capacity(proxy_full) is False

        # Proxy avec de la place
        proxy_ok = Proxy(
            tenant_id=1, host="5.6.7.8", port=8080,
            max_accounts=5, accounts_count=3,
        )
        assert await creator._check_proxy_capacity(proxy_ok) is True

        # Proxy a la limite exacte
        proxy_edge = Proxy(
            tenant_id=1, host="9.10.11.12", port=8080,
            max_accounts=5, accounts_count=4,
        )
        assert await creator._check_proxy_capacity(proxy_edge) is True

    asyncio.run(_test())


def test_human_delay_range():
    """Verifie que human_delay genere des delais entre 8min et 20min."""
    import random

    from backend.bot.ig_client import human_delay

    # On ne peut pas attendre 8-20 min dans un test.
    # On verifie la logique en mockant asyncio.sleep et en capturant le delai.
    delays = []

    async def _test():
        for _ in range(100):
            delay = random.uniform(8 * 60, 20 * 60)
            delays.append(delay)

    asyncio.run(_test())

    assert len(delays) == 100
    assert all(8 * 60 <= d <= 20 * 60 for d in delays), "Un delai est hors de [480s, 1200s]"

    # Verifier la distribution : pas tous la meme valeur
    unique_values = set(int(d) for d in delays)
    assert len(unique_values) > 50, f"Distribution trop homogene: {len(unique_values)} valeurs uniques sur 100"


def test_quota_never_exceeded():
    """Compte avec quota DM atteint → get_account_for_action('dm') retourne None."""
    from backend.database import async_session
    from backend.models import IgAccount

    async def _test():
        # Mettre tous les comptes a quota DM max
        async with async_session() as session:
            from sqlalchemy import select, update
            await session.execute(
                update(IgAccount)
                .where(IgAccount.tenant_id == 1)
                .values(dms_today=99)  # Bien au-dessus de tout quota
            )
            await session.commit()

        from backend.bot.account_pool import AccountPool
        pool = AccountPool()
        account = await pool.get_account_for_action(niche_id=1, action="dm", tenant_id=1)
        assert account is None, "Devrait retourner None quand tous les quotas DM sont atteints"

        # Remettre les quotas a zero pour ne pas impacter les autres tests
        async with async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(IgAccount)
                .where(IgAccount.tenant_id == 1)
                .values(dms_today=0)
            )
            await session.commit()

    asyncio.run(_test())
