from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from intelligent_search_agent.app.routes import (
    admin_router,
    assets_router,
    chat_router,
    documents_router,
    meetings_router,
    search_router,
)
from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.core.logging import setup_logging
from intelligent_search_agent.db import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield
    await Database.close_pool()


settings = get_settings()
app = FastAPI(title=settings.api_title, lifespan=lifespan)
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(assets_router)
app.include_router(documents_router)
app.include_router(meetings_router)
app.include_router(search_router)
app.include_router(admin_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "environment": settings.environment,
        "model": settings.openai_model,
        "asset_storage_backend": settings.asset_storage_backend,
    }


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; frame-src 'self' https:; connect-src 'self'",
    )
    return response
