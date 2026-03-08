"""
ScrapingScheduler — Lance le pipeline automatiquement toutes les heures.

- Actif entre 9h et 20h (Europe/Paris)
- Pour chaque niche active en DB
- Respecte daily_limit par niche (defaut 200 prospects/jour)
- Log les resultats dans pipeline_runs
- Skip les niches qui ont deja atteint leur daily_limit
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.database import async_session, init_db
from backend.models import Niche, PipelineRun
from backend.scrapers.pipeline import ScrapingPipeline

logger = logging.getLogger("instafarm.scheduler")

PARIS_TZ = ZoneInfo("Europe/Paris")

# Heures d'activite (Paris)
HOUR_START = 9
HOUR_END = 20

# Limite quotidienne de prospects collectes par niche
DEFAULT_DAILY_LIMIT = 200

# Limite par run (pour eviter un run trop long)
PER_RUN_LIMIT = 50

# Intervalle entre runs (secondes)
RUN_INTERVAL = 3600  # 1 heure


def _now_paris() -> datetime:
    """Heure actuelle en timezone Paris."""
    return datetime.now(PARIS_TZ)


def _is_active_hour() -> bool:
    """Retourne True si on est entre HOUR_START et HOUR_END (Paris)."""
    hour = _now_paris().hour
    return HOUR_START <= hour < HOUR_END


def _today_start_utc() -> datetime:
    """Minuit Paris en UTC pour le jour courant."""
    now = _now_paris()
    midnight_paris = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_paris.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


async def get_daily_collected(tenant_id: int, niche_id: int, sector: str) -> int:
    """Total de prospects collectes aujourd'hui pour une niche."""
    today_utc = _today_start_utc()
    async with async_session() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(PipelineRun.collected), 0)).where(
                PipelineRun.tenant_id == tenant_id,
                PipelineRun.niche_id == niche_id,
                PipelineRun.ran_at >= today_utc,
            )
        )
        return result.scalar_one()


async def get_active_niches() -> list[Niche]:
    """Recupere toutes les niches actives de tous les tenants."""
    async with async_session() as session:
        result = await session.execute(
            select(Niche).where(Niche.status == "active")
        )
        return list(result.scalars().all())


def niche_to_run_params(niche: Niche) -> dict:
    """Convertit un objet Niche en dict pour le pipeline."""
    cities = json.loads(niche.target_cities or "[]")
    city = cities[0] if cities else ""

    # Deduire le sector depuis le nom : "Restaurants" -> "restaurant"
    sector = niche.name.lower().rstrip("s")

    return {
        "tenant_id": niche.tenant_id,
        "niche_id": niche.id,
        "name": niche.name,
        "sector": sector,
        "city": city,
        "departement": "",
        "limit": PER_RUN_LIMIT,
    }


async def run_once(
    sector: str | None = None,
    city: str | None = None,
    tenant_id: int | None = None,
    niche_id: int | None = None,
    limit: int = PER_RUN_LIMIT,
    force: bool = False,
) -> dict:
    """
    Execute un seul run du pipeline.

    Args:
        sector: nom du secteur (ex: "restaurant")
        city: ville cible (ex: "Lyon")
        tenant_id: ID tenant (default 1)
        niche_id: ID niche (default: lookup par sector)
        limit: max prospects a collecter
        force: ignorer les verifications (heures, daily_limit)

    Returns:
        dict avec stats du run + pipeline_run_id
    """
    await init_db()  # S'assurer que les tables existent

    tenant_id = tenant_id or 1

    # Trouver la niche en DB si niche_id non fourni
    if not niche_id and sector:
        async with async_session() as session:
            result = await session.execute(
                select(Niche).where(
                    Niche.tenant_id == tenant_id,
                    func.lower(Niche.name).like(f"%{sector.lower()}%"),
                )
            )
            niche_row = result.scalars().first()
            if niche_row:
                niche_id = niche_row.id
            else:
                return {"error": f"Niche '{sector}' non trouvee pour tenant {tenant_id}"}

    if not niche_id:
        return {"error": "niche_id ou sector requis"}

    # Verifier heure active (sauf force)
    if not force and not _is_active_hour():
        hour = _now_paris().hour
        return {"skipped": True, "reason": f"Hors heures actives ({hour}h, actif {HOUR_START}h-{HOUR_END}h)"}

    # Verifier daily_limit (sauf force)
    effective_sector = sector or "unknown"
    if not force:
        daily_collected = await get_daily_collected(tenant_id, niche_id, effective_sector)
        if daily_collected >= DEFAULT_DAILY_LIMIT:
            return {
                "skipped": True,
                "reason": f"Daily limit atteint ({daily_collected}/{DEFAULT_DAILY_LIMIT})",
            }

    # Construire les params du pipeline
    niche_dict = {
        "tenant_id": tenant_id,
        "niche_id": niche_id,
        "name": effective_sector.capitalize(),
        "sector": effective_sector,
        "city": city or "",
        "departement": "",
        "limit": limit,
    }

    # Lancer le pipeline
    pipeline = ScrapingPipeline()
    t0 = time.monotonic()
    error_msg = None

    try:
        stats = await pipeline.run_for_niche(niche_dict)
    except Exception as e:
        logger.error(f"[Scheduler] Pipeline crash pour {effective_sector}/{city}: {e}")
        stats = {"collected": 0, "instagram_found": 0, "validated": 0, "saved": 0}
        error_msg = str(e)

    duration = time.monotonic() - t0

    # Sauvegarder le run en DB
    run_id = await _save_pipeline_run(
        tenant_id=tenant_id,
        niche_id=niche_id,
        sector=effective_sector,
        city=city or "",
        stats=stats,
        duration=duration,
        error=error_msg,
    )

    result = {
        "pipeline_run_id": run_id,
        "sector": effective_sector,
        "city": city or "",
        "collected": stats.get("collected", 0),
        "instagram_found": stats.get("instagram_found", 0),
        "validated": stats.get("validated", 0),
        "queued": stats.get("saved", 0),
        "duration_sec": round(duration, 1),
        "error": error_msg,
    }

    logger.info(
        f"[Scheduler] Run termine: {effective_sector}/{city} — "
        f"collected={result['collected']} ig={result['instagram_found']} "
        f"valid={result['validated']} ({result['duration_sec']}s)"
    )

    return result


async def _save_pipeline_run(
    tenant_id: int,
    niche_id: int,
    sector: str,
    city: str,
    stats: dict,
    duration: float,
    error: str | None,
) -> int:
    """Insere un PipelineRun en DB et retourne son ID."""
    async with async_session() as session:
        run = PipelineRun(
            tenant_id=tenant_id,
            niche_id=niche_id,
            sector=sector,
            city=city,
            collected=stats.get("collected", 0),
            instagram_found=stats.get("instagram_found", 0),
            validated=stats.get("validated", 0),
            queued=stats.get("saved", 0),
            duration_sec=round(duration, 1),
            error=error,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def run_all_niches():
    """
    Execute le pipeline pour toutes les niches actives.
    Appelé par le scheduler toutes les heures.
    """
    if not _is_active_hour():
        hour = _now_paris().hour
        logger.info(f"[Scheduler] Hors heures actives ({hour}h), skip")
        return

    niches = await get_active_niches()
    logger.info(f"[Scheduler] {len(niches)} niches actives a traiter")

    for niche in niches:
        params = niche_to_run_params(niche)
        sector = params["sector"]
        city = params["city"]
        tenant_id = params["tenant_id"]
        niche_id = params["niche_id"]

        # Verifier daily limit
        daily_collected = await get_daily_collected(tenant_id, niche_id, sector)
        if daily_collected >= DEFAULT_DAILY_LIMIT:
            logger.info(
                f"[Scheduler] Skip {sector}/{city}: daily limit atteint "
                f"({daily_collected}/{DEFAULT_DAILY_LIMIT})"
            )
            continue

        # Calculer la limite restante
        remaining = DEFAULT_DAILY_LIMIT - daily_collected
        params["limit"] = min(PER_RUN_LIMIT, remaining)

        logger.info(f"[Scheduler] Lancement pipeline: {sector}/{city} (limit={params['limit']})")

        try:
            result = await run_once(
                sector=sector,
                city=city,
                tenant_id=tenant_id,
                niche_id=niche_id,
                limit=params["limit"],
                force=True,  # On a deja verifie les heures et le daily limit
            )
            logger.info(f"[Scheduler] Resultat {sector}/{city}: {result}")
        except Exception as e:
            logger.error(f"[Scheduler] Erreur {sector}/{city}: {e}")

        # Pause entre niches pour eviter surcharge
        await asyncio.sleep(5)

    logger.info("[Scheduler] Cycle termine")


async def start_scheduler():
    """
    Boucle principale du scheduler.
    Tourne indefiniment, execute run_all_niches() toutes les heures.
    """
    await init_db()
    logger.info(f"[Scheduler] Demarre (actif {HOUR_START}h-{HOUR_END}h Paris, intervalle={RUN_INTERVAL}s)")

    while True:
        try:
            await run_all_niches()
        except Exception as e:
            logger.error(f"[Scheduler] Erreur cycle: {e}")

        # Attendre l'intervalle
        logger.info(f"[Scheduler] Prochain cycle dans {RUN_INTERVAL}s")
        await asyncio.sleep(RUN_INTERVAL)


# ============================================================
# Point d'entree CLI : python -m backend.scrapers.scheduler
# ============================================================
if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    # Mode run unique : python -m backend.scrapers.scheduler --once restaurant Lyon
    if "--once" in sys.argv:
        idx = sys.argv.index("--once")
        sector = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "restaurant"
        city = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else ""
        limit = int(sys.argv[idx + 3]) if len(sys.argv) > idx + 3 else PER_RUN_LIMIT

        async def _run_once():
            result = await run_once(sector=sector, city=city, limit=limit, force=True)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        asyncio.run(_run_once())
    else:
        # Mode daemon
        asyncio.run(start_scheduler())
