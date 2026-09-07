"""FastAPI application entry point."""

from fastapi import FastAPI

from runcoach import __version__
from runcoach.api.routes.analytics import router as analytics_router
from runcoach.api.routes.authentication import router as authentication_router
from runcoach.api.routes.coaching import router as coaching_router
from runcoach.api.routes.health import router as health_router
from runcoach.api.routes.onboarding import router as onboarding_router
from runcoach.config import get_settings


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Running-performance analytics and coaching API.",
    )
    application.include_router(authentication_router)
    application.include_router(analytics_router)
    application.include_router(coaching_router)
    application.include_router(onboarding_router)
    application.include_router(health_router)
    return application


app = create_app()
