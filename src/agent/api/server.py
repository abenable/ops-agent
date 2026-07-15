"""Uvicorn entry point for the FastAPI app."""

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status

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
app.include_router(router)


def run_api():
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
