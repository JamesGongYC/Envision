"""ASGI FastAPI app factory for agent SSE endpoints."""
from __future__ import annotations

from fastapi import FastAPI

from agents.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Envision agent API", version="0.1.0")
    app.include_router(router)
    return app
