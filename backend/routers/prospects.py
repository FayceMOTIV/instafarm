"""Prospects : liste, detail, update, blacklist, export CSV."""

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import Message, Prospect, Tenant

router = APIRouter(prefix="/api/prospects", tags=["prospects"])


class ProspectUpdate(BaseModel):
    notes: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    rdv_date: str | None = None


@router.get("")
async def list_prospects(
    status: str | None = None,
    niche_id: int | None = None,
    score_min: float | None = None,
    city: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    query = select(Prospect).where(Prospect.tenant_id == tenant.id)

    if status:
        query = query.where(Prospect.status == status)
    if niche_id:
        query = query.where(Prospect.niche_id == niche_id)
    if score_min is not None:
        query = query.where(Prospect.score >= score_min)
    if city:
        query = query.where(Prospect.city == city)

    # Total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Pagination
    query = query.order_by(Prospect.score.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    prospects = result.scalars().all()

    return {
        "prospects": [_prospect_to_dict(p) for p in prospects],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 0,
    }


@router.get("/export")
async def export_csv(
    status: str | None = None,
    niche_id: int | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    query = select(Prospect).where(Prospect.tenant_id == tenant.id)
    if status:
        query = query.where(Prospect.status == status)
    if niche_id:
        query = query.where(Prospect.niche_id == niche_id)

    query = query.order_by(Prospect.score.desc())
    result = await db.execute(query)
    prospects = result.scalars().all()

    # Generer CSV avec BOM UTF-8 (compatible Excel FR)
    output = io.StringIO()
    output.write("\ufeff")  # BOM UTF-8

    writer = csv.writer(output, delimiter=",")
    writer.writerow([
        "username", "bio", "followers", "niche_id", "status", "score",
        "city", "first_dm_at", "last_reply_at", "notes", "tags", "rdv_date",
    ])

    for p in prospects:
        writer.writerow([
            p.username,
            (p.bio or "")[:200],
            p.followers,
            p.niche_id,
            p.status,
            round(p.score, 4),
            p.city or "",
            p.first_dm_at.isoformat() if p.first_dm_at else "",
            p.last_reply_at.isoformat() if p.last_reply_at else "",
            p.notes or "",
            p.tags or "[]",
            p.rdv_date.isoformat() if p.rdv_date else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=prospects_export.csv"},
    )


@router.get("/{prospect_id}")
async def get_prospect(
    prospect_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await _get_tenant_prospect(db, tenant.id, prospect_id)

    # Historique messages
    msg_result = await db.execute(
        select(Message)
        .where(Message.prospect_id == prospect_id, Message.tenant_id == tenant.id)
        .order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()

    return {
        "prospect": _prospect_to_dict(prospect),
        "messages": [_message_to_dict(m) for m in messages],
    }


@router.patch("/{prospect_id}")
async def update_prospect(
    prospect_id: int,
    body: ProspectUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await _get_tenant_prospect(db, tenant.id, prospect_id)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "tags" and value is not None:
            setattr(prospect, field, json.dumps(value, ensure_ascii=False))
        elif field == "rdv_date" and value is not None:
            setattr(prospect, field, datetime.fromisoformat(value))
        else:
            setattr(prospect, field, value)

    await db.commit()
    await db.refresh(prospect)
    return _prospect_to_dict(prospect)


@router.post("/{prospect_id}/blacklist")
async def blacklist_prospect(
    prospect_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await _get_tenant_prospect(db, tenant.id, prospect_id)
    prospect.status = "blacklisted"
    await db.commit()
    return {"id": prospect_id, "status": "blacklisted"}


def _prospect_to_dict(p: Prospect) -> dict:
    return {
        "id": p.id,
        "instagram_id": p.instagram_id,
        "username": p.username,
        "full_name": p.full_name,
        "bio": p.bio,
        "followers": p.followers,
        "following": p.following,
        "posts_count": p.posts_count,
        "has_link_in_bio": p.has_link_in_bio,
        "score": p.score,
        "score_details": json.loads(p.score_details) if p.score_details else {},
        "status": p.status,
        "city": p.city,
        "notes": p.notes,
        "tags": json.loads(p.tags) if p.tags else [],
        "niche_id": p.niche_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _message_to_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "direction": m.direction,
        "content": m.content,
        "status": m.status,
        "ab_variant": m.ab_variant,
        "is_relance": m.is_relance,
        "relance_number": m.relance_number,
        "generated_by": m.generated_by,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _get_tenant_prospect(db: AsyncSession, tenant_id: int, prospect_id: int) -> Prospect:
    result = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant_id)
    )
    prospect = result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect non trouve")
    return prospect
