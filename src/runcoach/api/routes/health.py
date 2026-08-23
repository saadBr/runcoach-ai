"""Liveness and database-readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from runcoach.config import Settings, get_settings
from runcoach.db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])

SettingsDependency = Annotated[Settings, Depends(get_settings)]
DatabaseSessionDependency = Annotated[Session, Depends(get_db_session)]


class LivenessResponse(BaseModel):
    """Response returned when the API process is alive."""

    status: Literal["ok"]
    service: str
    environment: str


class ReadinessResponse(LivenessResponse):
    """Response returned when the API and database are ready."""

    database: Literal["ok"]


@router.get("/live", response_model=LivenessResponse)
def liveness(settings: SettingsDependency) -> LivenessResponse:
    """Report whether the API process is running."""

    return LivenessResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
def readiness(
    settings: SettingsDependency,
    database_session: DatabaseSessionDependency,
) -> ReadinessResponse:
    """Report whether the API can execute a database query."""

    try:
        database_session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        ) from error

    return ReadinessResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        database="ok",
    )
