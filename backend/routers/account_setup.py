"""Endpoints API pour la gestion des comptes TikTok."""

import asyncio
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/api/tiktok/accounts", tags=["TikTok Accounts"])


class CreateAccountRequest(BaseModel):
    niche: str
    proxy: str | None = None
    headless: bool = True


@router.post("/create")
async def create_account(req: CreateAccountRequest, background_tasks: BackgroundTasks):
    """Cree un nouveau compte TikTok pour une niche."""

    async def _create():
        from backend.firebase import db
        from backend.tiktok.account_creator import create_tiktok_account, setup_account_in_firebase

        result = await create_tiktok_account(
            niche=req.niche,
            proxy=req.proxy,
            headless=req.headless,
        )
        if result["success"]:
            await setup_account_in_firebase(result, db)

    background_tasks.add_task(asyncio.ensure_future, _create())
    return {"message": f"Creation compte {req.niche} demarree en arriere-plan"}


@router.post("/create-all")
async def create_all_accounts(background_tasks: BackgroundTasks):
    """Cree un compte pour chaque niche non configuree."""
    from backend.tiktok.config import TIKTOK_NICHE_CONFIG
    from backend.firebase import db

    niches_sans_compte = []
    for niche in TIKTOK_NICHE_CONFIG:
        doc = db.collection("tiktok_accounts").document(niche).get()
        if doc.exists and not doc.to_dict().get("username"):
            niches_sans_compte.append(niche)

    async def _create_all():
        from backend.tiktok.account_creator import create_tiktok_account, setup_account_in_firebase
        from backend.firebase import db as firebase_db

        for niche in niches_sans_compte:
            print(f"\nCreation compte {niche}...")
            result = await create_tiktok_account(niche=niche, headless=True)
            if result["success"]:
                await setup_account_in_firebase(result, firebase_db)
            else:
                print(f"  ECHEC {niche}: {result['error']}")
            await asyncio.sleep(60)

    background_tasks.add_task(asyncio.ensure_future, _create_all())
    return {"message": f"Creation de {len(niches_sans_compte)} comptes demarree", "niches": niches_sans_compte}


@router.get("/status")
async def get_accounts_status():
    """Retourne le statut de tous les comptes TikTok."""
    from backend.firebase import db
    from backend.tiktok.cookies_manager import check_cookies_validity

    accounts = {}
    docs = db.collection("tiktok_accounts").stream()

    for doc in docs:
        if doc.id == "_meta":
            continue
        data = doc.to_dict()
        niche = doc.id

        cookies_info = {}
        if data.get("cookies_path"):
            validity = await check_cookies_validity(data["cookies_path"])
            cookies_info = {
                "valid": validity["valid"],
                "days_remaining": validity.get("days_remaining", 0),
                "needs_renewal": validity.get("needs_renewal", False),
            }

        accounts[niche] = {
            "username": data.get("username"),
            "status": data.get("status", "setup"),
            "warmup_day": data.get("warmup_day", 0),
            "daily_dm_count": data.get("daily_dm_count", 0),
            "total_dms_sent": data.get("total_dms_sent", 0),
            "videos_published": data.get("videos_published", 0),
            "cookies": cookies_info,
        }

    return accounts
