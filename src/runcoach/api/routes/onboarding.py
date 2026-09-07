"""Required private Strava-history onboarding endpoints."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from runcoach.api.routes.authentication import (
    DatabaseSessionDependency,
    OnboardingAthleteDependency,
)
from runcoach.config import get_settings
from runcoach.onboarding.service import OnboardingError, StravaOnboardingService
from runcoach.onboarding.strava_archive import MAX_ARCHIVE_BYTES

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])


class OnboardingResponse(BaseModel):
    """Privacy-minimized result of required history ingestion and plan creation."""

    model_config = ConfigDict(extra="forbid")

    status: str
    canonical_runs: int = Field(ge=0)
    sensor_runs: int = Field(ge=0)
    parser_findings: int = Field(ge=0)
    plan_id: UUID


async def _store_bounded_archive(request: Request, destination: Path) -> None:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Archive content length is invalid.",
            ) from error
        if declared_size > MAX_ARCHIVE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The Strava archive exceeds the upload limit.",
            )

    written = 0
    with destination.open("wb") as archive_file:
        async for chunk in request.stream():
            written += len(chunk)
            if written > MAX_ARCHIVE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="The Strava archive exceeds the upload limit.",
                )
            archive_file.write(chunk)
    if written == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A non-empty Strava history ZIP is required.",
        )


@router.post("/strava-archive", response_model=OnboardingResponse)
async def upload_strava_archive(
    request: Request,
    identity: OnboardingAthleteDependency,
    database_session: DatabaseSessionDependency,
) -> OnboardingResponse:
    """Validate a raw ZIP upload and build the athlete's first evidence-backed plan."""

    encoded_name = request.headers.get("X-RunCoach-Filename", "strava-export.zip")
    filename = unquote(encoded_name)
    if not filename.casefold().endswith(".zip") or Path(filename).name != filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Upload the original Strava export as a ZIP file.",
        )

    private_root = get_settings().private_data_dir
    private_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="onboarding-", dir=private_root) as temporary_directory:
        temporary_root = Path(temporary_directory)
        archive_path = temporary_root / "strava-export.zip"
        await _store_bounded_archive(request, archive_path)
        try:
            completed = StravaOnboardingService(database_session).process_archive(
                athlete_id=identity.athlete_id,
                archive_path=archive_path,
                extraction_directory=temporary_root / "extracted",
            )
        except OnboardingError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": error.code, "message": str(error)},
            ) from error

    return OnboardingResponse(
        status=completed.status,
        canonical_runs=completed.canonical_runs,
        sensor_runs=completed.sensor_runs,
        parser_findings=completed.parser_findings,
        plan_id=completed.plan_id,
    )
