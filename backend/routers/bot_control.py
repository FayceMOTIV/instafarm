"""Bot control : status, pause, resume, queues."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import IgAccount, Niche, Tenant

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/status")
async def bot_status(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Status global du bot + pool comptes."""
    # Comptes par status
    account_result = await db.execute(
        select(IgAccount.status, func.count(IgAccount.id))
        .where(IgAccount.tenant_id == tenant.id)
        .group_by(IgAccount.status)
    )
    accounts_by_status = {row[0]: row[1] for row in account_result.all()}

    # Niches actives
    active_niches = await db.execute(
        select(func.count(Niche.id)).where(
            Niche.tenant_id == tenant.id, Niche.status == "active"
        )
    )
    active_count = active_niches.scalar() or 0

    total_accounts = sum(accounts_by_status.values())

    return {
        "bot_active": active_count > 0,
        "active_niches": active_count,
        "accounts": {
            "total": total_accounts,
            **accounts_by_status,
        },
    }


@router.post("/pause")
async def pause_bot(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Pause toutes les niches du tenant."""
    result = await db.execute(
        select(Niche).where(Niche.tenant_id == tenant.id, Niche.status == "active")
    )
    niches = result.scalars().all()
    for n in niches:
        n.status = "paused"
    await db.commit()
    return {"status": "paused", "niches_paused": len(niches)}


@router.post("/resume")
async def resume_bot(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Resume toutes les niches pausees du tenant."""
    result = await db.execute(
        select(Niche).where(Niche.tenant_id == tenant.id, Niche.status == "paused")
    )
    niches = result.scalars().all()
    for n in niches:
        n.status = "active"
    await db.commit()
    return {"status": "resumed", "niches_resumed": len(niches)}


@router.get("/queues")
async def queue_status(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Etat des queues Redis (placeholder si Redis pas connecte)."""
    return {
        "queues": {
            "dm_queue": {"pending": 0, "processing": 0},
            "scrape_queue": {"pending": 0, "processing": 0},
            "follow_queue": {"pending": 0, "processing": 0},
        },
        "redis_connected": False,
        "message": "Redis non connecte en mode dev",
    }
