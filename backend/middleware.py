"""Auth middleware : tenant API key + admin token + rate limiting."""

import os
import time
from collections import defaultdict
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.database import get_db
from backend.models import Tenant

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin_secret_token_change_me")

# Routes publiques (pas besoin d'auth)
PUBLIC_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}
PUBLIC_PREFIXES = ("/pwa", "/js", "/css")

# Rate limiting config
RATE_LIMIT_WINDOW = 60  # secondes
RATE_LIMIT_MAX_REQUESTS = 120  # requetes par fenetre


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting par IP — 120 req/min."""

    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Nettoyer les anciennes entrees
        self._requests[client_ip] = [
            t for t in self._requests[client_ip]
            if now - t < RATE_LIMIT_WINDOW
        ]

        if len(self._requests[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
            return JSONResponse(
                {"error": "Rate limit exceeded. Max 120 requests per minute."},
                status_code=429,
            )

        self._requests[client_ip].append(now)
        response = await call_next(request)
        return response


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware ASGI pour isolation multi-tenant.
    - Routes publiques : passent sans auth
    - Routes /admin : verifient ADMIN_TOKEN
    - Routes API : verifient Bearer token → injectent tenant_id dans request.state
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Routes publiques
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Routes admin
        if path.startswith("/admin"):
            auth_header = request.headers.get("authorization", "")
            token = auth_header.replace("Bearer ", "")
            if token != ADMIN_TOKEN:
                return JSONResponse({"error": "Admin token invalide"}, status_code=403)
            return await call_next(request)

        # Routes API — extraire tenant depuis Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        api_key = auth_header[7:]

        # Injecter le tenant_id dans request.state pour usage en downstream
        request.state.api_key = api_key
        response = await call_next(request)
        return response


async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """
    Extrait le tenant depuis le header Authorization: Bearer {api_key}.
    Retourne 401 si absent ou invalide.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header requis")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format: Bearer {api_key}")

    api_key = authorization[7:]
    result = await db.execute(
        select(Tenant).where(Tenant.api_key == api_key, Tenant.status != "deleted")
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=401, detail="API key invalide")

    if tenant.status == "suspended":
        raise HTTPException(status_code=403, detail="Compte suspendu")

    return tenant


async def verify_admin_token(
    authorization: Annotated[str | None, Header()] = None,
):
    """Verifie le token admin pour les routes /admin."""
    if not authorization:
        raise HTTPException(status_code=403, detail="Admin token requis")

    token = authorization.replace("Bearer ", "")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token invalide")
