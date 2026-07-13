from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, ws_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    """Create the single modular FastAPI backend used by dashboards and apps."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    origins = [
        origin.strip()
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router)

    logger = get_logger(__name__)
    logger.info(
        "backend_app_created",
        extra={
            "environment": settings.environment,
            "debug": settings.debug,
        },
    )
    return app


app = create_app()
