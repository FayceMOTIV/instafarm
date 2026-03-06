"""Tests Session 1 — DB + Seeds + API Health."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Ajouter le dossier racine au path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Forcer un chemin DB de test
TEST_DB_PATH = ROOT_DIR / "instafarm_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Cree la DB de test, seed tenant + niches, puis nettoie apres."""
    # Supprimer l'ancienne DB de test si elle existe
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import Niche, Tenant

    async def _setup():
        await init_db()

        # Seed tenant
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

        # Seed niches — importer les donnees
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

    # Cleanup
    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


EXPECTED_TABLES = [
    "tenants",
    "niches",
    "ig_accounts",
    "proxies",
    "prospects",
    "messages",
    "ab_variants",
    "webhooks",
    "system_logs",
]


def test_database_created():
    """Verifie que instafarm_test.db existe et contient toutes les tables."""
    assert TEST_DB_PATH.exists(), f"DB file not found at {TEST_DB_PATH}"

    conn = sqlite3.connect(str(TEST_DB_PATH))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    for table in EXPECTED_TABLES:
        assert table in tables, f"Table '{table}' manquante. Tables trouvees: {tables}"

    # Au moins 9 tables metier (sans compter les tables systeme SQLite)
    metier_tables = [t for t in tables if not t.startswith("sqlite_")]
    assert len(metier_tables) >= 9, f"Seulement {len(metier_tables)} tables trouvees: {metier_tables}"


def test_niches_seeded():
    """Verifie que les 10 niches sont creees en DB."""
    conn = sqlite3.connect(str(TEST_DB_PATH))

    cursor = conn.execute("SELECT COUNT(*) FROM niches WHERE tenant_id = 1;")
    count = cursor.fetchone()[0]
    assert count == 10, f"Attendu 10 niches, trouve {count}"

    # Verifier que "Restaurants" est la avec ses hashtags
    cursor = conn.execute("SELECT hashtags FROM niches WHERE name = 'Restaurants' AND tenant_id = 1;")
    row = cursor.fetchone()
    assert row is not None, "Niche 'Restaurants' non trouvee"

    hashtags = json.loads(row[0])
    assert "#restaurant" in hashtags, f"Hashtag #restaurant manquant dans {hashtags}"

    conn.close()


def test_tenant_seeded():
    """Verifie que le tenant de test existe."""
    conn = sqlite3.connect(str(TEST_DB_PATH))

    cursor = conn.execute(
        "SELECT name, plan, status, max_niches, max_accounts, max_dms_day FROM tenants WHERE email = 'admin@instafarm.io';"
    )
    row = cursor.fetchone()
    conn.close()

    assert row is not None, "Tenant admin@instafarm.io non trouve"
    name, plan, status, max_niches, max_accounts, max_dms_day = row

    assert name == "InstaFarm Solo Test"
    assert plan == "war_machine"
    assert status == "active"
    assert max_niches == 10
    assert max_accounts == 30
    assert max_dms_day == 900


def test_api_health():
    """Verifie que l'API tourne et repond sur /health."""
    import httpx

    # Lancer uvicorn en arriere-plan
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--port", "8765",
            "--log-level", "error",
        ],
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DB_PATH}"},
    )

    try:
        # Attendre que le serveur demarre
        for _ in range(30):
            time.sleep(0.5)
            try:
                resp = httpx.get("http://127.0.0.1:8765/health", timeout=2)
                if resp.status_code == 200:
                    break
            except httpx.ConnectError:
                continue
        else:
            pytest.fail("Serveur uvicorn n'a pas demarre en 15s")

        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"
        assert "env" in data
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_db_indexes():
    """Verifie que les index sont crees."""
    conn = sqlite3.connect(str(TEST_DB_PATH))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = [row[0] for row in cursor.fetchall()]
    conn.close()

    expected_indexes = [
        "idx_prospects_tenant_status",
        "idx_prospects_instagram_id",
        "idx_messages_prospect",
        "idx_ig_accounts_tenant_status",
        "idx_niches_tenant",
    ]

    for idx in expected_indexes:
        assert idx in indexes, f"Index '{idx}' manquant. Index trouves: {indexes}"
