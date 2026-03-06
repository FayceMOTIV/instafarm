"""Super Admin : gestion tenants + stats globales + kill-switch."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import verify_admin_token
from backend.models import Message, Niche, Prospect, SystemLog, Tenant

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_token)])


class TenantCreate(BaseModel):
    name: str
    email: str
    plan: str = "starter"  # starter | growth | war_machine


class TenantUpdate(BaseModel):
    plan: str | None = None
    status: str | None = None
    max_niches: int | None = None
    max_accounts: int | None = None
    max_dms_day: int | None = None


# Limites par plan
PLAN_LIMITS = {
    "starter":      {"max_niches": 3,  "max_accounts": 5,  "max_dms_day": 100},
    "growth":       {"max_niches": 5,  "max_accounts": 15, "max_dms_day": 450},
    "war_machine":  {"max_niches": 10, "max_accounts": 30, "max_dms_day": 900},
}


@router.get("/tenants")
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).order_by(Tenant.id))
    tenants = result.scalars().all()

    return {
        "tenants": [
            {
                "id": t.id,
                "name": t.name,
                "email": t.email,
                "plan": t.plan,
                "status": t.status,
                "max_niches": t.max_niches,
                "max_accounts": t.max_accounts,
                "max_dms_day": t.max_dms_day,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tenants
        ]
    }


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    # Verifier email unique
    existing = await db.execute(select(Tenant).where(Tenant.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email deja utilise")

    limits = PLAN_LIMITS.get(body.plan, PLAN_LIMITS["starter"])
    api_key = f"sk_{uuid.uuid4().hex[:24]}"

    tenant = Tenant(
        name=body.name,
        email=body.email,
        api_key=api_key,
        plan=body.plan,
        status="trial",
        trial_ends_at=datetime.utcnow() + timedelta(days=14),
        max_niches=limits["max_niches"],
        max_accounts=limits["max_accounts"],
        max_dms_day=limits["max_dms_day"],
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "email": tenant.email,
        "api_key": tenant.api_key,
        "plan": tenant.plan,
        "status": tenant.status,
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant non trouve")

    updates = body.model_dump(exclude_unset=True)

    # Si le plan change, mettre a jour les limites
    if "plan" in updates:
        limits = PLAN_LIMITS.get(updates["plan"], {})
        for key, value in limits.items():
            if key not in updates:
                setattr(tenant, key, value)

    for field, value in updates.items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)

    return {
        "id": tenant.id,
        "name": tenant.name,
        "plan": tenant.plan,
        "status": tenant.status,
        "max_niches": tenant.max_niches,
        "max_accounts": tenant.max_accounts,
        "max_dms_day": tenant.max_dms_day,
    }


@router.get("/stats")
async def global_stats(db: AsyncSession = Depends(get_db)):
    """MRR, DAU, DMs total, erreurs critiques."""
    # Total tenants par status
    tenant_result = await db.execute(
        select(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status)
    )
    tenants_by_status = {row[0]: row[1] for row in tenant_result.all()}

    # Total DMs envoyes
    dms_result = await db.execute(
        select(func.count(Message.id)).where(Message.direction == "outbound")
    )
    total_dms = dms_result.scalar() or 0

    # Erreurs critiques (dernieres 24h)
    since_24h = datetime.utcnow() - timedelta(hours=24)
    errors_result = await db.execute(
        select(func.count(SystemLog.id)).where(
            SystemLog.level.in_(["ERROR", "CRITICAL"]),
            SystemLog.created_at >= since_24h,
        )
    )
    critical_errors = errors_result.scalar() or 0

    # MRR estime (actifs * prix moyen)
    active_count = tenants_by_status.get("active", 0)
    mrr_estimate = active_count * 199  # Prix moyen growth plan

    return {
        "tenants": tenants_by_status,
        "total_dms_sent": total_dms,
        "critical_errors_24h": critical_errors,
        "mrr_estimate_eur": mrr_estimate,
    }


@router.post("/kill-switch")
async def kill_switch(db: AsyncSession = Depends(get_db)):
    """Pause TOUT le bot globalement."""
    # Mettre toutes les niches en pause
    result = await db.execute(select(Niche).where(Niche.status == "active"))
    niches = result.scalars().all()
    paused_count = 0
    for niche in niches:
        niche.status = "paused"
        paused_count += 1

    await db.commit()

    log = SystemLog(
        tenant_id=None,
        level="CRITICAL",
        module="admin",
        message=f"KILL SWITCH active : {paused_count} niches mises en pause",
        details="{}",
    )
    db.add(log)
    await db.commit()

    return {"status": "killed", "niches_paused": paused_count}
