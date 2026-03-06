"""Webhooks sortants : CRUD."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import Tenant, Webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: str
    events: list[str]  # ["prospect.interested", "rdv.booked", ...]


@router.get("")
async def list_webhooks(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Webhook).where(Webhook.tenant_id == tenant.id).order_by(Webhook.id)
    )
    webhooks = result.scalars().all()

    return {
        "webhooks": [
            {
                "id": w.id,
                "url": w.url,
                "events": json.loads(w.events),
                "status": w.status,
                "fail_count": w.fail_count,
                "last_triggered": w.last_triggered.isoformat() if w.last_triggered else None,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in webhooks
        ]
    }


@router.post("", status_code=201)
async def create_webhook(
    body: WebhookCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    webhook = Webhook(
        tenant_id=tenant.id,
        url=body.url,
        events=json.dumps(body.events, ensure_ascii=False),
        secret=str(uuid.uuid4()),
        status="active",
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    return {
        "id": webhook.id,
        "url": webhook.url,
        "events": json.loads(webhook.events),
        "secret": webhook.secret,
        "status": webhook.status,
    }


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.tenant_id == tenant.id)
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook non trouve")

    await db.delete(webhook)
    await db.commit()
    return {"deleted": True, "id": webhook_id}
