import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.middleware import RateLimitMiddleware, TenantMiddleware
from backend.routers import accounts, admin, analytics, bot_control, catalog, messages, niches, prospects, tiktok, webhooks
from backend.routers import account_setup

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")


_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise la DB + Firebase + Scheduler au demarrage."""
    global _scheduler
    await init_db()

    # Firebase seed pour TikTok pipeline
    try:
        from backend.firebase import db as firebase_db
        from backend.tiktok.firebase_seed import seed_firebase_if_needed
        seed_firebase_if_needed(firebase_db)

        # Scheduler prod
        from backend.tiktok.scheduler_prod import setup_scheduler
        _scheduler = setup_scheduler(firebase_db)
        _scheduler.start()
        print("[STARTUP] Scheduler demarre")
    except Exception as e:
        print(f"[STARTUP] Firebase/Scheduler skipped: {e}")

    yield

    # Shutdown
    if _scheduler:
        _scheduler.shutdown()
        print("[SHUTDOWN] Scheduler arrete")


app = FastAPI(
    title="InstaFarm War Machine",
    version="1.0.0",
    lifespan=lifespan,
)

# Middlewares (ordre inverse : le dernier ajoute s'execute en premier)
# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if APP_ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 2. Rate limiting (120 req/min par IP)
app.add_middleware(RateLimitMiddleware)
# 3. Tenant isolation
app.add_middleware(TenantMiddleware)

# Routers API (auth tenant via middleware)
app.include_router(niches.router)
app.include_router(prospects.router)
app.include_router(messages.router)
app.include_router(analytics.router)
app.include_router(accounts.router)
app.include_router(webhooks.router)
app.include_router(bot_control.router)

# Router TikTok (generation videos)
app.include_router(tiktok.router, prefix="/api/tiktok", tags=["tiktok"])

# Router TikTok Accounts (creation + status)
app.include_router(account_setup.router)

# Router Catalog (public — pas d'auth)
app.include_router(catalog.router)

# Router Admin (auth admin token)
app.include_router(admin.router)


@app.get("/health")
async def health():
    from datetime import datetime, timezone

    checks = {
        "server": "ok",
        "version": "1.0.0",
        "env": APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "firebase": "unknown",
        "scheduler": "unknown",
    }

    try:
        from backend.firebase import db as firebase_db
        firebase_db.collection("tiktok_accounts").limit(1).get()
        checks["firebase"] = "ok"
    except Exception as e:
        checks["firebase"] = f"error: {str(e)[:100]}"

    if _scheduler and _scheduler.running:
        checks["scheduler"] = f"ok ({len(_scheduler.get_jobs())} jobs)"
    else:
        checks["scheduler"] = "stopped"

    all_ok = checks["firebase"] == "ok" and "ok" in checks["scheduler"]
    checks["status"] = "healthy" if all_ok else "degraded"

    return checks


# Serve PWA static files (after API routes to avoid conflicts)
PWA_DIR = Path(__file__).resolve().parent.parent / "pwa"
if PWA_DIR.is_dir():
    app.mount("/js", StaticFiles(directory=PWA_DIR / "js"), name="pwa-js")
    app.mount("/css", StaticFiles(directory=PWA_DIR / "css"), name="pwa-css")

    @app.get("/")
    async def root():
        return FileResponse(PWA_DIR / "index.html")
else:

    @app.get("/")
    async def root():
        return {"app": "InstaFarm War Machine", "version": "1.0.0", "env": APP_ENV, "status": "running"}
