"""Uvicorn entry point for the FastAPI app."""

from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agent.api.routes import router
from agent.config.settings import settings


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Shared-secret dependency. Disabled when API_KEY is not configured."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header",
        )


app = FastAPI(
    title="Marconi Ops Agent API",
    dependencies=[Depends(_require_api_key)],
)
# ponytail: dev-only CORS for the Vite frontend on :5173; tighten WEB_ORIGIN in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in [settings.web_origin, "http://localhost:5173"] if o],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

# Serve the built web UI (web/dist) at / when it exists, so the agent can run as
# one process in production. In dev, the Vite server on :5173 proxies /api here.
_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")


def run_api():
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
