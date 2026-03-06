"""Analytics : dashboard ROI, funnel, heatmap, A/B test, niche ranking."""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware import get_current_tenant
from backend.models import AbVariant, Message, Niche, Prospect, Tenant

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(
    period: str = Query("last_7_days", regex="^(last_7_days|last_30_days|all_time)$"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """ROI dashboard + stats globales."""
    # Calculer la date de debut selon la periode
    if period == "last_7_days":
        since = datetime.utcnow() - timedelta(days=7)
        prev_since = since - timedelta(days=7)
    elif period == "last_30_days":
        since = datetime.utcnow() - timedelta(days=30)
        prev_since = since - timedelta(days=30)
    else:
        since = datetime(2020, 1, 1)
        prev_since = since

    # Stats globales pour la periode
    global_stats = await _compute_period_stats(db, tenant.id, since)

    # Stats periode precedente (pour comparaison)
    prev_stats = await _compute_period_stats(db, tenant.id, prev_since, since)

    # ROI
    hot_prospects = global_stats["interested"]
    closing_rate = 15  # %
    avg_basket = 500  # EUR
    estimated_pipeline = int(hot_prospects * (closing_rate / 100) * avg_basket)

    # Stats par niche
    niche_result = await db.execute(
        select(Niche).where(Niche.tenant_id == tenant.id).order_by(Niche.response_rate.desc())
    )
    niches = niche_result.scalars().all()

    by_niche = []
    for rank, n in enumerate(niches, 1):
        by_niche.append({
            "niche_id": n.id,
            "name": n.name,
            "emoji": n.emoji,
            "dms_sent": n.total_dms_sent,
            "response_rate_pct": round(n.response_rate * 100, 1) if n.response_rate else 0.0,
            "interested": n.total_interested,
            "rank": rank,
        })

    # Changements vs periode precedente
    dms_change = 0.0
    rr_change = 0.0
    if prev_stats["dms_sent"] > 0:
        dms_change = round(((global_stats["dms_sent"] - prev_stats["dms_sent"]) / prev_stats["dms_sent"]) * 100, 1)
    if prev_stats["response_rate_pct"] > 0:
        rr_change = round(global_stats["response_rate_pct"] - prev_stats["response_rate_pct"], 1)

    return {
        "period": period,
        "roi": {
            "hot_prospects": hot_prospects,
            "estimated_pipeline_eur": estimated_pipeline,
            "closing_rate_pct": closing_rate,
            "avg_basket_eur": avg_basket,
            "calculation": f"{hot_prospects} x {closing_rate}% x {avg_basket}EUR",
        },
        "global": global_stats,
        "vs_previous_period": {
            "dms_change_pct": dms_change,
            "response_rate_change_pct": rr_change,
        },
        "by_niche": by_niche,
    }


@router.get("/funnel")
async def funnel(
    niche_id: int | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Funnel complet par niche ou global."""
    query = select(Prospect.status, func.count(Prospect.id)).where(
        Prospect.tenant_id == tenant.id
    )
    if niche_id:
        query = query.where(Prospect.niche_id == niche_id)

    query = query.group_by(Prospect.status)
    result = await db.execute(query)
    funnel_data = {row[0]: row[1] for row in result.all()}

    # Ordre du funnel
    ordered_statuses = [
        "scraped", "scored", "followed", "follow_back",
        "dm_sent", "replied", "interested", "rdv", "converted", "lost", "blacklisted",
    ]

    return {
        "funnel": [
            {"status": s, "count": funnel_data.get(s, 0)}
            for s in ordered_statuses
        ],
        "niche_id": niche_id,
    }


@router.get("/heatmap")
async def heatmap(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Donnees heatmap 24h x 7j (quand les DMs obtiennent des reponses)."""
    # Compter les reponses par jour de semaine et heure
    result = await db.execute(
        select(
            func.strftime("%w", Message.created_at).label("dow"),
            func.strftime("%H", Message.created_at).label("hour"),
            func.count(Message.id),
        )
        .where(
            Message.tenant_id == tenant.id,
            Message.direction == "inbound",
        )
        .group_by("dow", "hour")
    )

    heatmap_data = []
    for row in result.all():
        heatmap_data.append({
            "day_of_week": int(row[0]),
            "hour": int(row[1]),
            "count": row[2],
        })

    return {"heatmap": heatmap_data}


@router.get("/ab-test")
async def ab_test_results(
    niche_id: int | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Resultats A/B testing."""
    query = select(AbVariant).where(AbVariant.tenant_id == tenant.id)
    if niche_id:
        query = query.where(AbVariant.niche_id == niche_id)

    result = await db.execute(query.order_by(AbVariant.response_rate.desc()))
    variants = result.scalars().all()

    return {
        "variants": [
            {
                "id": v.id,
                "niche_id": v.niche_id,
                "variant_letter": v.variant_letter,
                "template": v.template[:100],
                "sends": v.sends,
                "responses": v.responses,
                "response_rate": round(v.response_rate * 100, 1) if v.response_rate else 0.0,
                "is_winner": v.is_winner,
                "status": v.status,
            }
            for v in variants
        ]
    }


@router.get("/niche-ranking")
async def niche_ranking(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Classement niches par performance."""
    result = await db.execute(
        select(Niche).where(Niche.tenant_id == tenant.id).order_by(Niche.response_rate.desc())
    )
    niches = result.scalars().all()

    return {
        "ranking": [
            {
                "rank": i + 1,
                "niche_id": n.id,
                "name": n.name,
                "emoji": n.emoji,
                "total_dms_sent": n.total_dms_sent,
                "total_responses": n.total_responses,
                "response_rate_pct": round(n.response_rate * 100, 1) if n.response_rate else 0.0,
                "total_interested": n.total_interested,
                "best_send_hour": n.best_send_hour,
            }
            for i, n in enumerate(niches)
        ]
    }


async def _compute_period_stats(
    db: AsyncSession,
    tenant_id: int,
    since: datetime,
    until: datetime | None = None,
) -> dict:
    """Calcule les stats pour une periode donnee."""
    until = until or datetime.utcnow()

    # DMs envoyes
    dms_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant_id,
            Message.direction == "outbound",
            Message.created_at >= since,
            Message.created_at < until,
        )
    )
    dms_sent = dms_result.scalar() or 0

    # Reponses recues
    responses_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant_id,
            Message.direction == "inbound",
            Message.created_at >= since,
            Message.created_at < until,
        )
    )
    responses = responses_result.scalar() or 0

    # Prospects par status
    status_counts = {}
    for s in ["interested", "rdv", "converted"]:
        result = await db.execute(
            select(func.count(Prospect.id)).where(
                Prospect.tenant_id == tenant_id,
                Prospect.status == s,
                Prospect.created_at >= since,
                Prospect.created_at < until,
            )
        )
        status_counts[s] = result.scalar() or 0

    response_rate = round((responses / dms_sent * 100), 1) if dms_sent > 0 else 0.0

    return {
        "dms_sent": dms_sent,
        "responses": responses,
        "response_rate_pct": response_rate,
        "interested": status_counts["interested"],
        "rdv_booked": status_counts["rdv"],
        "converted": status_counts["converted"],
    }
