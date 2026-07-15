"""Uvicorn entry point for the FastAPI app."""

import uvicorn

from agent.api.routes import router
from agent.config.settings import settings
from fastapi import FastAPI

app = FastAPI(title="Marconi Ops Agent API")
app.include_router(router)


def run_api():
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
