"""Seed le tenant de test pour InstaFarm."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select

from backend.database import async_session, init_db
from backend.models import Tenant

TEST_TENANT = {
    "name": "InstaFarm Solo Test",
    "email": "admin@instafarm.io",
    "api_key": "sk_test_warmachine_solo_2026",
    "plan": "war_machine",
    "status": "active",
    "max_niches": 10,
    "max_accounts": 30,
    "max_dms_day": 900,
}


async def seed_tenant():
    """Cree le tenant de test s'il n'existe pas."""
    await init_db()

    async with async_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.email == TEST_TENANT["email"])
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"[SKIP] Tenant '{existing.name}' existe deja (id={existing.id})")
            return

        tenant = Tenant(**TEST_TENANT)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        print(f"[OK] Tenant '{tenant.name}' cree (id={tenant.id}, plan={tenant.plan})")


if __name__ == "__main__":
    asyncio.run(seed_tenant())
