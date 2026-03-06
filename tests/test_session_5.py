"""Tests Session 5 — Scheduler, Anti-ban, Redis, Watchdog."""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

TEST_DB_PATH = ROOT_DIR / "instafarm_test_s5.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """DB de test avec tenant, niches, comptes, prospects, messages."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import IgAccount, Message, Niche, Prospect, SystemLog, Tenant

    async def _setup():
        await init_db()

        async with async_session() as session:
            # Tenant
            tenant = Tenant(
                name="Test S5", email="test_s5@instafarm.io",
                api_key="sk_test_s5", plan="war_machine", status="active",
            )
            session.add(tenant)
            await session.commit()

            # 3 niches
            for i, name in enumerate(["Restaurants", "Dentistes", "Garagistes"], 1):
                niche = Niche(
                    tenant_id=1, name=name, emoji="",
                    hashtags=f'["#{name.lower()}"]',
                    product_pitch=f"App {name}",
                    dm_prompt_system=f"Prompt {name}",
                    dm_fallback_templates='["Fallback"]',
                )
                session.add(niche)
            await session.commit()

            # Compte avec follow rate faible
            now = datetime.utcnow()
            account = IgAccount(
                tenant_id=1, niche_id=1, username="bot_s5_1", password="pass",
                status="active", warmup_day=18,
                created_at=now - timedelta(days=60),
                follows_today=0, dms_today=0, likes_today=0,
                action_blocks_week=0,
                total_follows=100,
            )
            session.add(account)
            await session.commit()

            # 100 prospects "followed" (mais quasi aucun follow-back) → follow rate low
            for i in range(100):
                p = Prospect(
                    tenant_id=1, niche_id=1,
                    instagram_id=f"ig_s5_fb_{i}",
                    username=f"user_fb_{i}",
                    status="followed",
                    followed_at=now - timedelta(hours=30),
                    score=0.5,
                )
                session.add(p)

            # 1 seul follow-back → 1% rate
            p_fb = Prospect(
                tenant_id=1, niche_id=1,
                instagram_id="ig_s5_fb_back",
                username="user_follow_back",
                status="follow_back",
                followed_at=now - timedelta(hours=30),
                follow_back_at=now - timedelta(hours=20),
                score=0.8,
            )
            session.add(p_fb)
            await session.commit()

            # Stats pour morning report
            for i in range(47):
                p = Prospect(
                    tenant_id=1, niche_id=1,
                    instagram_id=f"ig_s5_follow_{i}",
                    username=f"user_follow_{i}",
                    status="followed",
                    followed_at=now - timedelta(hours=2),
                    score=0.5,
                )
                session.add(p)
            await session.commit()

            # 12 DMs envoyes aujourd'hui
            for i in range(12):
                msg = Message(
                    tenant_id=1, prospect_id=1, ig_account_id=1,
                    direction="outbound", content=f"DM {i}",
                    status="sent", sent_at=now - timedelta(hours=1),
                )
                session.add(msg)
            # 8 reponses recues
            for i in range(8):
                msg = Message(
                    tenant_id=1, prospect_id=1, ig_account_id=1,
                    direction="inbound", content=f"Reply {i}",
                    status="delivered",
                )
                session.add(msg)
            await session.commit()

            # 3 prospects "interested"
            for i in range(3):
                p = Prospect(
                    tenant_id=1, niche_id=1,
                    instagram_id=f"ig_s5_hot_{i}",
                    username=f"hot_prospect_{i}",
                    status="interested",
                    score=0.9 - i * 0.1,
                    last_reply_at=now - timedelta(hours=1),
                )
                session.add(p)
            await session.commit()

    asyncio.run(_setup())
    yield

    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_scheduler_parallel_niches():
    """
    Mock 3 niches avec process_single_niche mocke.
    Verifie que asyncio.gather les lance en VRAI parallele.
    3 niches x 0.5s each → devrait prendre ~0.5s total, pas 1.5s.
    """
    from backend.bot.scheduler import InstaFarmScheduler

    async def _test():
        scheduler = InstaFarmScheduler()

        call_times = []

        async def mock_process_niche(niche, tenant_id):
            call_times.append(time.monotonic())
            await asyncio.sleep(0.5)  # Simule du travail

        with patch.object(scheduler, "_process_single_niche", side_effect=mock_process_niche):
            with patch("backend.bot.scheduler.check_active_hours", return_value=True):
                start = time.monotonic()
                await scheduler.process_all_niches(tenant_id=1)
                elapsed = time.monotonic() - start

        # 3 niches en parallele = ~0.5s, pas 1.5s
        assert elapsed < 1.2, f"Parallelisme echoue: {elapsed:.2f}s (devrait etre < 1.2s)"
        assert len(call_times) == 3, f"Attendu 3 niches traitees, obtenu {len(call_times)}"

        # Verifier que les 3 ont demarre quasi-simultanement
        if len(call_times) >= 2:
            max_gap = max(call_times) - min(call_times)
            assert max_gap < 0.2, f"Niches pas lancees en parallele, gap: {max_gap:.3f}s"

        print(f"\nParallelisme OK: 3 niches en {elapsed:.2f}s")

    asyncio.run(_test())


def test_active_hours_check():
    """
    11h00 Paris → True
    21h00 Paris → False
    08h59 Paris → False
    Jour ferie (1er janvier) → False
    """
    from backend.bot.scheduler import PARIS_TZ, check_active_hours

    # Mock datetime pour tester differentes heures
    import pytz

    # 11h00 Paris → True
    with patch("backend.bot.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 5, 11, 0, tzinfo=PARIS_TZ)
        assert check_active_hours() is True

    # 21h00 Paris → False
    with patch("backend.bot.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 5, 21, 0, tzinfo=PARIS_TZ)
        assert check_active_hours() is False

    # 08h59 Paris → False
    with patch("backend.bot.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 3, 5, 8, 59, tzinfo=PARIS_TZ)
        assert check_active_hours() is False

    # 1er janvier 14h00 → False (jour ferie)
    with patch("backend.bot.scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=PARIS_TZ)
        assert check_active_hours() is False


def test_redis_queue_isolation():
    """
    Pousse donnees dans tenant=1/niche=1.
    Verifie que tenant=2/niche=1 ne les voit pas.
    Note: Utilise mock Redis (fakeredis) pour eviter dependance Redis reel.
    """
    from backend.services.redis_service import RedisService

    async def _test():
        service = RedisService()

        # Mock Redis avec un dict en memoire
        store: dict[str, list[str]] = {}

        async def mock_rpush(key, value):
            store.setdefault(key, []).append(value)
            return len(store[key])

        async def mock_lpop(key):
            if key in store and store[key]:
                return store[key].pop(0)
            return None

        async def mock_llen(key):
            return len(store.get(key, []))

        mock_redis = AsyncMock()
        mock_redis.rpush = mock_rpush
        mock_redis.lpop = mock_lpop
        mock_redis.llen = mock_llen

        with patch("backend.services.redis_service.get_redis", return_value=mock_redis):
            # Push dans tenant=1, niche=1
            await service.push_to_queue(1, 1, "follow", {"prospect_id": 42})
            await service.push_to_queue(1, 1, "follow", {"prospect_id": 43})

            # Verifier tenant=1, niche=1 a 2 elements
            length_t1 = await service.get_queue_length(1, 1, "follow")
            assert length_t1 == 2, f"Tenant 1 devrait avoir 2 elements, a {length_t1}"

            # Verifier tenant=2, niche=1 est vide
            length_t2 = await service.get_queue_length(2, 1, "follow")
            assert length_t2 == 0, f"Tenant 2 devrait avoir 0 elements, a {length_t2}"

            # Pop de tenant=1
            item = await service.pop_from_queue(1, 1, "follow")
            assert item == {"prospect_id": 42}

            # Pop de tenant=2 → None
            item_t2 = await service.pop_from_queue(2, 1, "follow")
            assert item_t2 is None

    asyncio.run(_test())


def test_rate_limiting_redis():
    """
    Simule compte qui a atteint son quota DM du jour.
    is_rate_limited() → True.
    Apres reset → False.
    """
    from backend.services.redis_service import RedisService

    async def _test():
        service = RedisService()
        store: dict[str, str] = {}

        async def mock_get(key):
            return store.get(key)

        async def mock_incr(key):
            store[key] = str(int(store.get(key, "0")) + 1)
            return int(store[key])

        async def mock_expireat(key, timestamp):
            pass  # Mock

        async def mock_delete(key):
            store.pop(key, None)

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.incr = mock_incr
        mock_redis.expireat = mock_expireat
        mock_redis.delete = mock_delete

        with patch("backend.services.redis_service.get_redis", return_value=mock_redis):
            # Initial: pas rate limited
            assert await service.is_rate_limited(1, "dm", max_count=12) is False

            # Simuler 12 DMs
            for _ in range(12):
                await service.increment_rate_limit(1, "dm")

            # Maintenant rate limited
            assert await service.is_rate_limited(1, "dm", max_count=12) is True

            # Reset
            await service.reset_rate_limit(1, "dm")
            assert await service.is_rate_limited(1, "dm", max_count=12) is False

    asyncio.run(_test())


def test_watchdog_redis_failure():
    """Mock Redis pour qu'il fail sur PING. Verifie alerte CRITICAL en DB."""
    from backend.bot.watchdog import Watchdog
    from backend.database import async_session
    from backend.models import SystemLog

    async def _test():
        watchdog = Watchdog()

        # Mock Redis PING qui fail
        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = ConnectionError("Redis unreachable")

        with patch("backend.services.redis_service.get_redis", return_value=mock_redis):
            result = await watchdog._check_redis()

        assert result is False

        # Verifier qu'une alerte CRITICAL a ete loggee
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(SystemLog)
                .where(
                    SystemLog.level == "CRITICAL",
                    SystemLog.module == "watchdog",
                )
                .order_by(SystemLog.id.desc())
                .limit(1)
            )
            log = result.scalar_one_or_none()

        assert log is not None, "Aucune alerte CRITICAL trouvee en DB"
        assert "redis" in log.message.lower(), f"Message devrait mentionner redis: {log.message}"

    asyncio.run(_test())


def test_anti_ban_follow_rate():
    """
    Compte avec 100 follows et 1 follow-back (1%).
    check_account_health() → signal follow_rate_low = True.
    """
    from backend.bot.anti_ban import AntiBanEngine
    from backend.database import async_session
    from backend.models import IgAccount

    async def _test():
        engine = AntiBanEngine()

        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(IgAccount).where(IgAccount.username == "bot_s5_1")
            )
            account = result.scalar_one()

        health = await engine.check_account_health(account)

        assert health["signals"]["follow_rate_low"] is True, (
            f"follow_rate_low devrait etre True (1% < 2%), got {health['signals']}"
        )
        print(f"\nAnti-ban health: {health}")

    asyncio.run(_test())


def test_morning_report_content():
    """
    Verifie que send_morning_report genere le bon contenu.
    """
    from backend.bot.scheduler import InstaFarmScheduler

    async def _test():
        scheduler = InstaFarmScheduler()
        report = await scheduler.send_morning_report(tenant_id=1)

        assert "follows" in report.lower(), f"Report devrait mentionner follows: {report}"
        assert "DM" in report or "dm" in report.lower(), f"Report devrait mentionner DMs: {report}"
        assert "reponse" in report.lower(), f"Report devrait mentionner reponses: {report}"
        assert "@" in report, f"Report devrait mentionner un top prospect: {report}"

        print(f"\n{'='*60}")
        print(f"RAPPORT MATIN :")
        print(f"{'='*60}")
        print(report)
        print(f"{'='*60}")

    asyncio.run(_test())
