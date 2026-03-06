"""Comptes IG : liste, status, creation."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import IgAccount, Tenant

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IgAccount).where(IgAccount.tenant_id == tenant.id).order_by(IgAccount.id)
    )
    accounts = result.scalars().all()

    return {
        "accounts": [
            {
                "id": a.id,
                "username": a.username,
                "niche_id": a.niche_id,
                "status": a.status,
                "warmup_day": a.warmup_day,
                "ig_driver": a.ig_driver,
                "follows_today": a.follows_today,
                "dms_today": a.dms_today,
                "likes_today": a.likes_today,
                "total_follows": a.total_follows,
                "total_dms_sent": a.total_dms_sent,
                "total_bans": a.total_bans,
                "last_action": a.last_action.isoformat() if a.last_action else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in accounts
        ],
        "total": len(accounts),
    }


@router.get("/{account_id}/status")
async def account_status(
    account_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IgAccount).where(IgAccount.id == account_id, IgAccount.tenant_id == tenant.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Compte non trouve")

    return {
        "id": account.id,
        "username": account.username,
        "status": account.status,
        "warmup_day": account.warmup_day,
        "last_login": account.last_login.isoformat() if account.last_login else None,
        "last_action": account.last_action.isoformat() if account.last_action else None,
        "quotas": {
            "follows_today": account.follows_today,
            "dms_today": account.dms_today,
            "likes_today": account.likes_today,
        },
        "health": "ok" if account.status == "active" else account.status,
    }


@router.post("/create")
async def create_account(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # En prod, lancer en background task
    count_result = await db.execute(
        select(func.count(IgAccount.id)).where(IgAccount.tenant_id == tenant.id)
    )
    count = count_result.scalar() or 0

    if count >= tenant.max_accounts:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Limite de {tenant.max_accounts} comptes atteinte")

    return {"status": "queued", "message": "Creation de compte lancee en background"}
