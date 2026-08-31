"""FastAPI application entrypoint for the headless eCommerce API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic migrations (alembic upgrade head) — see the
    # migrations in alembic/versions/. Here we only ensure the super admin from
    # .env exists (idempotent, skipped if env values are blank).
    from app.core.database import AsyncSessionLocal
    from app.core.init_superadmin import ensure_superadmin

    async with AsyncSessionLocal() as session:
        await ensure_superadmin(session)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}


def main() -> None:
    """Run with: python -m app.main"""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
