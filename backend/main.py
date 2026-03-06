import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db
from backend.middleware import RateLimitMiddleware, TenantMiddleware
from backend.routers import accounts, admin, analytics, bot_control, messages, niches, prospects, webhooks

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise la DB au demarrage."""
    await init_db()
    yield


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

# Router Admin (auth admin token)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "env": APP_ENV}


@app.get("/")
async def root():
    return {
        "app": "InstaFarm War Machine",
        "version": "1.0.0",
        "env": APP_ENV,
        "status": "running",
    }


# Serve PWA static files (after API routes to avoid conflicts)
PWA_DIR = Path(__file__).resolve().parent.parent / "pwa"
if PWA_DIR.is_dir():
    app.mount("/js", StaticFiles(directory=PWA_DIR / "js"), name="pwa-js")
    app.mount("/css", StaticFiles(directory=PWA_DIR / "css"), name="pwa-css")
    app.mount("/pwa", StaticFiles(directory=PWA_DIR, html=True), name="pwa")
