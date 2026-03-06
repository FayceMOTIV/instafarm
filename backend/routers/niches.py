"""CRUD niches + stats + actions."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import Niche, Prospect, Tenant

router = APIRouter(prefix="/api/niches", tags=["niches"])


class NicheCreate(BaseModel):
    name: str
    emoji: str = ""
    hashtags: list[str]
    product_pitch: str
    dm_prompt_system: str
    dm_fallback_templates: list[str]
    scoring_vocab: list[str] = []
    target_cities: list[str] = []
    target_account_count: int = 3


class NicheUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None
    hashtags: list[str] | None = None
    product_pitch: str | None = None
    dm_prompt_system: str | None = None
    dm_fallback_templates: list[str] | None = None
    scoring_vocab: list[str] | None = None
    target_cities: list[str] | None = None
    target_account_count: int | None = None
    status: str | None = None


def _niche_to_dict(niche: Niche) -> dict:
    return {
        "id": niche.id,
        "name": niche.name,
        "emoji": niche.emoji,
        "status": niche.status,
        "hashtags": json.loads(niche.hashtags),
        "target_cities": json.loads(niche.target_cities),
        "target_account_count": niche.target_account_count,
        "product_pitch": niche.product_pitch,
        "scoring_vocab": json.loads(niche.scoring_vocab),
        "total_scraped": niche.total_scraped,
        "total_dms_sent": niche.total_dms_sent,
        "total_responses": niche.total_responses,
        "total_interested": niche.total_interested,
        "response_rate": niche.response_rate,
        "best_send_hour": niche.best_send_hour,
        "created_at": niche.created_at.isoformat() if niche.created_at else None,
    }


@router.get("")
async def list_niches(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Niche).where(Niche.tenant_id == tenant.id).order_by(Niche.id)
    )
    niches = result.scalars().all()
    return {"niches": [_niche_to_dict(n) for n in niches]}


@router.post("", status_code=201)
async def create_niche(
    body: NicheCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verifier limite plan
    count_result = await db.execute(
        select(func.count(Niche.id)).where(Niche.tenant_id == tenant.id)
    )
    count = count_result.scalar() or 0
    if count >= tenant.max_niches:
        raise HTTPException(status_code=400, detail=f"Limite de {tenant.max_niches} niches atteinte")

    niche = Niche(
        tenant_id=tenant.id,
        name=body.name,
        emoji=body.emoji,
        hashtags=json.dumps(body.hashtags, ensure_ascii=False),
        target_cities=json.dumps(body.target_cities, ensure_ascii=False),
        target_account_count=body.target_account_count,
        product_pitch=body.product_pitch,
        dm_prompt_system=body.dm_prompt_system,
        dm_fallback_templates=json.dumps(body.dm_fallback_templates, ensure_ascii=False),
        scoring_vocab=json.dumps(body.scoring_vocab, ensure_ascii=False),
    )
    db.add(niche)
    await db.commit()
    await db.refresh(niche)
    return _niche_to_dict(niche)


@router.get("/{niche_id}")
async def get_niche(
    niche_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)
    return _niche_to_dict(niche)


@router.patch("/{niche_id}")
async def update_niche(
    niche_id: int,
    body: NicheUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field in ("hashtags", "target_cities", "dm_fallback_templates", "scoring_vocab"):
            setattr(niche, field, json.dumps(value, ensure_ascii=False))
        else:
            setattr(niche, field, value)

    await db.commit()
    await db.refresh(niche)
    return _niche_to_dict(niche)


@router.delete("/{niche_id}")
async def delete_niche(
    niche_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)
    await db.delete(niche)
    await db.commit()
    return {"deleted": True, "id": niche_id}


@router.get("/{niche_id}/stats")
async def niche_stats(
    niche_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)

    # Compter prospects par status
    pipeline_result = await db.execute(
        select(Prospect.status, func.count(Prospect.id))
        .where(Prospect.tenant_id == tenant.id, Prospect.niche_id == niche_id)
        .group_by(Prospect.status)
    )
    pipeline = {row[0]: row[1] for row in pipeline_result.all()}

    return {
        "niche": _niche_to_dict(niche),
        "pipeline": pipeline,
        "total_prospects": sum(pipeline.values()),
    }


@router.post("/{niche_id}/pause")
async def toggle_pause(
    niche_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)
    niche.status = "paused" if niche.status == "active" else "active"
    await db.commit()
    return {"id": niche_id, "status": niche.status}


@router.post("/{niche_id}/scrape")
async def trigger_scrape(
    niche_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    niche = await _get_tenant_niche(db, tenant.id, niche_id)
    # En prod, lancer en background task. Pour l'instant, retourner acknowledgment.
    return {"status": "queued", "niche_id": niche_id, "message": f"Scraping {niche.name} lance en background"}


async def _get_tenant_niche(db: AsyncSession, tenant_id: int, niche_id: int) -> Niche:
    """Helper : recupere une niche en verifiant l'isolation tenant."""
    result = await db.execute(
        select(Niche).where(Niche.id == niche_id, Niche.tenant_id == tenant_id)
    )
    niche = result.scalar_one_or_none()
    if not niche:
        raise HTTPException(status_code=404, detail="Niche non trouvee")
    return niche
