"""Tests Session 6 — API FastAPI complete + Analytics."""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Ajouter le dossier racine au path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Forcer DB de test + admin token
TEST_DB_PATH = ROOT_DIR / "instafarm_test_s6.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["ADMIN_TOKEN"] = "test_admin_token_s6"

# Tenant API key de test
TENANT_API_KEY = "sk_test_warmachine_solo_2026"
ADMIN_TOKEN = "test_admin_token_s6"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Cree la DB de test, seed tenant + niches + data de test."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    from backend.database import async_session, engine, init_db
    from backend.models import IgAccount, Message, Niche, Prospect, Tenant

    async def _setup():
        await init_db()

        async with async_session() as session:
            # Tenant 1 (notre tenant de test)
            tenant1 = Tenant(
                name="InstaFarm Solo Test",
                email="admin@instafarm.io",
                api_key=TENANT_API_KEY,
                plan="war_machine",
                status="active",
                max_niches=10,
                max_accounts=30,
                max_dms_day=900,
            )
            session.add(tenant1)
            await session.flush()

            # Tenant 2 (pour test isolation)
            tenant2 = Tenant(
                name="Other Tenant",
                email="other@example.com",
                api_key="sk_other_tenant_key",
                plan="starter",
                status="active",
                max_niches=3,
                max_accounts=5,
                max_dms_day=100,
            )
            session.add(tenant2)
            await session.flush()

            # Niche pour tenant 1
            niche1 = Niche(
                tenant_id=1,
                name="Restaurants",
                emoji="\U0001f37d\ufe0f",
                hashtags='["#restaurant"]',
                product_pitch="App restaurant",
                dm_prompt_system="Tu es expert",
                dm_fallback_templates='["Bonjour"]',
                scoring_vocab='["restaurant"]',
                total_dms_sent=127,
                total_responses=12,
                total_interested=5,
                response_rate=0.094,
            )
            session.add(niche1)
            await session.flush()

            # Prospects pour tenant 1 (5 interested + 3 scored)
            for i in range(5):
                p = Prospect(
                    tenant_id=1,
                    niche_id=1,
                    instagram_id=f"interested_{i}",
                    username=f"resto_interested_{i}",
                    bio=f"Restaurant {i} à Lyon",
                    followers=1000 + i * 100,
                    following=300,
                    posts_count=50,
                    score=0.8 - i * 0.05,
                    status="interested",
                    city="Lyon",
                )
                session.add(p)

            for i in range(3):
                p = Prospect(
                    tenant_id=1,
                    niche_id=1,
                    instagram_id=f"scored_{i}",
                    username=f"resto_scored_{i}",
                    bio="Restaurant scored",
                    followers=800,
                    following=200,
                    posts_count=30,
                    score=0.6,
                    status="scored",
                )
                session.add(p)

            # Prospect pour tenant 2 (pour test isolation)
            p_other = Prospect(
                tenant_id=2,
                niche_id=1,
                instagram_id="other_tenant_prospect",
                username="other_resto",
                bio="Secret restaurant",
                followers=500,
                following=100,
                posts_count=20,
                score=0.7,
                status="scored",
            )
            session.add(p_other)
            await session.flush()

            # 50 messages pour test pagination
            for i in range(50):
                msg = Message(
                    tenant_id=1,
                    prospect_id=1,
                    ig_account_id=0,
                    direction="outbound" if i % 2 == 0 else "inbound",
                    content=f"Message test {i}",
                    status="sent",
                    generated_by="manual",
                )
                session.add(msg)

            # Messages outbound recents (pour analytics)
            for i in range(10):
                msg = Message(
                    tenant_id=1,
                    prospect_id=1,
                    ig_account_id=0,
                    direction="outbound",
                    content=f"DM recent {i}",
                    status="sent",
                    generated_by="groq",
                    created_at=datetime.utcnow() - timedelta(days=2),
                )
                session.add(msg)

            # Messages inbound (reponses)
            for i in range(3):
                msg = Message(
                    tenant_id=1,
                    prospect_id=1,
                    ig_account_id=0,
                    direction="inbound",
                    content=f"Reponse {i}",
                    status="delivered",
                    generated_by="manual",
                    created_at=datetime.utcnow() - timedelta(days=1),
                )
                session.add(msg)

            await session.commit()

    asyncio.run(_setup())
    yield

    async def _cleanup():
        await engine.dispose()

    asyncio.run(_cleanup())
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def _get_app():
    from backend.main import app
    return app


# ===== TEST 1 : Auth required =====
def test_auth_required():
    """Toutes les routes /api/* -> 401 sans Authorization header."""
    async def _test():
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            routes_to_test = [
                ("GET", "/api/niches"),
                ("GET", "/api/prospects"),
                ("GET", "/api/messages"),
                ("GET", "/api/analytics/dashboard"),
                ("GET", "/api/bot/status"),
                ("GET", "/api/accounts"),
                ("GET", "/api/webhooks"),
            ]
            for method, path in routes_to_test:
                if method == "GET":
                    resp = await client.get(path)
                assert resp.status_code == 401, f"{path} devrait retourner 401, obtenu {resp.status_code}"
                print(f"  [AUTH] {method} {path} → 401 OK")

    asyncio.run(_test())


# ===== TEST 2 : Auth valid =====
def test_auth_valid():
    """Authorization: Bearer sk_test_warmachine_solo_2026 -> 200."""
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/niches", headers=headers)
            assert resp.status_code == 200, f"Attendu 200, obtenu {resp.status_code}: {resp.text}"
            data = resp.json()
            assert "niches" in data
            print(f"\n[AUTH] GET /api/niches → 200 OK, {len(data['niches'])} niches")

    asyncio.run(_test())


# ===== TEST 3 : Tenant isolation =====
def test_tenant_isolation_api():
    """Tenant 1 ne peut pas acceder aux prospects du tenant 2."""
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/prospects", headers=headers)
            data = resp.json()

            # Verifier qu'aucun prospect du tenant 2 n'apparait
            usernames = [p["username"] for p in data["prospects"]]
            assert "other_resto" not in usernames, "Prospect du tenant 2 visible par tenant 1 !"
            print(f"\n[ISOLATION] {len(data['prospects'])} prospects visibles (aucun du tenant 2)")

    asyncio.run(_test())


# ===== TEST 4 : Niches CRUD =====
def test_niches_crud():
    """Create/Read/Update/Delete une niche via API."""
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # CREATE
            new_niche = {
                "name": "Fleuristes",
                "emoji": "\U0001f490",
                "hashtags": ["#fleuriste", "#bouquet"],
                "product_pitch": "App fleuriste",
                "dm_prompt_system": "Tu es expert fleurs",
                "dm_fallback_templates": ["Bonjour fleuriste"],
                "scoring_vocab": ["fleur", "bouquet"],
            }
            resp = await client.post("/api/niches", json=new_niche, headers=headers)
            assert resp.status_code == 201, f"Create failed: {resp.text}"
            created = resp.json()
            niche_id = created["id"]
            print(f"\n[CRUD] CREATE niche Fleuristes → id={niche_id}")

            # READ
            resp = await client.get(f"/api/niches/{niche_id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["name"] == "Fleuristes"
            print(f"[CRUD] READ niche {niche_id} → OK")

            # UPDATE
            resp = await client.patch(
                f"/api/niches/{niche_id}",
                json={"emoji": "\U0001f33b"},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["emoji"] == "\U0001f33b"
            print(f"[CRUD] UPDATE niche {niche_id} emoji → OK")

            # DELETE
            resp = await client.delete(f"/api/niches/{niche_id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["deleted"] is True
            print(f"[CRUD] DELETE niche {niche_id} → OK")

            # Verify deleted
            resp = await client.get(f"/api/niches/{niche_id}", headers=headers)
            assert resp.status_code == 404

    asyncio.run(_test())


# ===== TEST 5 : Analytics dashboard =====
def test_analytics_dashboard():
    """
    GET /api/analytics/dashboard.
    Verifie structure JSON et calcul ROI.
    MONTRE la reponse JSON dans le terminal.
    """
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/analytics/dashboard?period=last_7_days", headers=headers)
            assert resp.status_code == 200
            data = resp.json()

            # Verifier structure
            assert "period" in data
            assert "roi" in data
            assert "global" in data
            assert "vs_previous_period" in data
            assert "by_niche" in data

            # Verifier ROI structure
            roi = data["roi"]
            assert "hot_prospects" in roi
            assert "estimated_pipeline_eur" in roi
            assert "closing_rate_pct" in roi

            # Verifier global stats structure
            g = data["global"]
            assert "dms_sent" in g
            assert "responses" in g
            assert "response_rate_pct" in g

            print(f"\n[ANALYTICS] Dashboard response:")
            print(json.dumps(data, indent=2, ensure_ascii=False))

    asyncio.run(_test())


# ===== TEST 6 : Inbox pagination =====
def test_inbox_pagination():
    """
    GET /api/messages?page=1&limit=20 -> 20 messages.
    GET /api/messages?page=2&limit=20 -> 20 messages.
    """
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Page 1
            resp1 = await client.get("/api/messages?page=1&limit=20", headers=headers)
            assert resp1.status_code == 200
            data1 = resp1.json()
            assert len(data1["messages"]) == 20, f"Page 1: attendu 20, obtenu {len(data1['messages'])}"
            assert data1["total"] >= 50  # Au moins 50 messages inseres

            # Page 2
            resp2 = await client.get("/api/messages?page=2&limit=20", headers=headers)
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert len(data2["messages"]) == 20, f"Page 2: attendu 20, obtenu {len(data2['messages'])}"

            # Verifier que page 1 et 2 sont differentes
            ids_1 = {m["id"] for m in data1["messages"]}
            ids_2 = {m["id"] for m in data2["messages"]}
            assert ids_1.isdisjoint(ids_2), "Pages 1 et 2 contiennent les memes messages"

            print(f"\n[PAGINATION] Page 1: {len(data1['messages'])} messages, Page 2: {len(data2['messages'])} messages")
            print(f"  Total: {data1['total']}, Pages: {data1['pages']}")

    asyncio.run(_test())


# ===== TEST 7 : Export CSV =====
def test_export_csv():
    """
    GET /api/prospects/export?status=interested.
    Verifie : Content-Type csv, 5 lignes de donnees, BOM UTF-8.
    """
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {TENANT_API_KEY}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/prospects/export?status=interested", headers=headers)
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")

            content = resp.text
            # Verifier BOM UTF-8
            assert content.startswith("\ufeff"), "BOM UTF-8 manquant"

            lines = content.strip().split("\n")
            header = lines[0].replace("\ufeff", "")
            data_lines = lines[1:]

            assert "username" in header
            assert "score" in header
            assert len(data_lines) == 5, f"Attendu 5 lignes de donnees, obtenu {len(data_lines)}"

            print(f"\n[CSV] Export: {len(data_lines)} prospects interested")
            print(f"  Header: {header[:80]}...")
            print(f"  Ligne 1: {data_lines[0][:80]}...")

    asyncio.run(_test())


# ===== TEST 8 : Admin protected =====
def test_admin_protected():
    """GET /admin/tenants sans ADMIN_TOKEN -> 403."""
    async def _test():
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Sans token
            resp = await client.get("/admin/tenants")
            assert resp.status_code == 403, f"Attendu 403, obtenu {resp.status_code}"

            # Mauvais token
            resp = await client.get("/admin/tenants", headers={"Authorization": "Bearer wrong_token"})
            assert resp.status_code == 403

            print(f"\n[ADMIN] /admin/tenants sans token → 403 OK")
            print(f"[ADMIN] /admin/tenants mauvais token → 403 OK")

    asyncio.run(_test())


# ===== TEST 9 : Admin create tenant =====
def test_admin_create_tenant():
    """POST /admin/tenants cree tenant en DB. Verifie api_key generee automatiquement."""
    async def _test():
        app = _get_app()
        headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            new_tenant = {
                "name": "New Client SaaS",
                "email": "newclient@example.com",
                "plan": "growth",
            }
            resp = await client.post("/admin/tenants", json=new_tenant, headers=headers)
            assert resp.status_code == 201, f"Create tenant failed: {resp.text}"
            data = resp.json()

            assert data["name"] == "New Client SaaS"
            assert data["email"] == "newclient@example.com"
            assert data["plan"] == "growth"
            assert data["status"] == "trial"
            assert data["api_key"].startswith("sk_"), f"API key format invalide: {data['api_key']}"
            assert len(data["api_key"]) > 10

            print(f"\n[ADMIN] Tenant cree: {data['name']}")
            print(f"  API Key: {data['api_key']}")
            print(f"  Plan: {data['plan']}, Status: {data['status']}")

    asyncio.run(_test())
