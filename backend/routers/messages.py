"""Inbox unifiee + conversations + envoi manuel + suggestion IA."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import Message, Prospect, Niche, Tenant

router = APIRouter(prefix="/api/messages", tags=["messages"])


class SendMessage(BaseModel):
    content: str


class SuggestRequest(BaseModel):
    prospect_id: int
    last_message: str


@router.get("")
async def inbox(
    niche_id: int | None = None,
    direction: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Inbox unifiee : tous les messages, toutes les niches."""
    query = select(Message).where(Message.tenant_id == tenant.id)

    if niche_id:
        # Filtrer par niche via prospect
        prospect_ids_q = select(Prospect.id).where(
            Prospect.tenant_id == tenant.id, Prospect.niche_id == niche_id
        )
        query = query.where(Message.prospect_id.in_(prospect_ids_q))

    if direction:
        query = query.where(Message.direction == direction)

    # Total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Pagination — plus recents en premier
    query = query.order_by(Message.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    messages = result.scalars().all()

    return {
        "messages": [_msg_to_dict(m) for m in messages],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 0,
    }


@router.get("/{prospect_id}")
async def conversation(
    prospect_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Conversation complete avec un prospect."""
    # Verifier que le prospect appartient au tenant
    prospect = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant.id)
    )
    if not prospect.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Prospect non trouve")

    result = await db.execute(
        select(Message)
        .where(Message.prospect_id == prospect_id, Message.tenant_id == tenant.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return {"prospect_id": prospect_id, "messages": [_msg_to_dict(m) for m in messages]}


@router.post("/{prospect_id}")
async def send_manual_message(
    prospect_id: int,
    body: SendMessage,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Envoyer un message manuel (depuis PWA)."""
    prospect = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant.id)
    )
    if not prospect.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Prospect non trouve")

    message = Message(
        tenant_id=tenant.id,
        prospect_id=prospect_id,
        ig_account_id=0,  # Manuel = pas de compte IG attache
        direction="outbound",
        content=body.content,
        status="pending",
        generated_by="manual",
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return _msg_to_dict(message)


@router.post("/suggest")
async def suggest_response(
    body: SuggestRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Suggestion IA pour repondre a un prospect (bouton PWA)."""
    # Recuperer prospect + niche
    prospect_result = await db.execute(
        select(Prospect).where(Prospect.id == body.prospect_id, Prospect.tenant_id == tenant.id)
    )
    prospect = prospect_result.scalar_one_or_none()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect non trouve")

    niche_result = await db.execute(select(Niche).where(Niche.id == prospect.niche_id))
    niche = niche_result.scalar_one_or_none()

    try:
        from backend.services.groq_service import GroqService
        groq = GroqService()
        suggestion = await groq.suggest_response(prospect, niche, body.last_message)
    except Exception:
        suggestion = "Merci pour votre retour ! Est-ce qu'un appel de 15min cette semaine vous conviendrait ?"

    return {"suggestion": suggestion}


def _msg_to_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "prospect_id": m.prospect_id,
        "ig_account_id": m.ig_account_id,
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
