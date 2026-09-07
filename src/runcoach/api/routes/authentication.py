"""Account login, session inspection, and logout endpoints."""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from runcoach.analytics.performance import PerformanceLabel, StandardDistance
from runcoach.db.identity import (
    AuthenticatedAthlete,
    AuthenticationRejectedError,
    AuthenticationService,
    IdentityConflictError,
    IdentityError,
    NewAthleteRegistration,
    NewAthleteRegistrationService,
)
from runcoach.db.session import get_db_session

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
bearer_scheme = HTTPBearer(auto_error=False)

DatabaseSessionDependency = Annotated[Session, Depends(get_db_session)]
BearerCredentialsDependency = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]


class AuthenticationModel(BaseModel):
    """Strict API contract for authentication requests and responses."""

    model_config = ConfigDict(extra="forbid")


class LoginRequest(AuthenticationModel):
    """Credentials submitted to open a revocable session."""

    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)


class RegistrationRequest(AuthenticationModel):
    """Identity, goal, and verified benchmark required before archive upload."""

    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=1024)
    timezone: str = Field(min_length=1, max_length=64)
    goal_distance: StandardDistance
    race_date: date
    target_time_seconds: int | None = Field(default=None, gt=0)
    days_per_week: int = Field(ge=3, le=7)
    benchmark_distance: StandardDistance
    benchmark_elapsed_time_seconds: float = Field(gt=0)
    benchmark_date: date
    benchmark_label: PerformanceLabel
    research_consent: bool = False


class AthleteIdentityResponse(AuthenticationModel):
    """Non-secret athlete identity shown after authentication."""

    display_name: str | None
    timezone: str
    onboarding_status: str


class LoginResponse(AuthenticationModel):
    """Opaque bearer token returned only when a login session is created."""

    access_token: str = Field(min_length=32)
    token_type: Literal["bearer"]
    expires_at: datetime
    athlete: AthleteIdentityResponse


class CurrentAccountResponse(AuthenticationModel):
    """Current athlete context resolved exclusively from the bearer session."""

    athlete: AthleteIdentityResponse
    session_expires_at: datetime


def _athlete_response(identity: AuthenticatedAthlete) -> AthleteIdentityResponse:
    return AthleteIdentityResponse(
        display_name=identity.display_name,
        timezone=identity.timezone,
        onboarding_status=identity.onboarding_status,
    )


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticated_athlete(
    credentials: BearerCredentialsDependency,
    database_session: DatabaseSessionDependency,
) -> AuthenticatedAthlete:
    """Resolve a bearer credential to the athlete identity owned by that session."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _authentication_required()
    try:
        return AuthenticationService(database_session).authenticate(credentials.credentials)
    except AuthenticationRejectedError as error:
        raise _authentication_required() from error
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from error


AuthenticatedAthleteDependency = Annotated[
    AuthenticatedAthlete,
    Depends(authenticated_athlete),
]


def onboarding_athlete(
    credentials: BearerCredentialsDependency,
    database_session: DatabaseSessionDependency,
) -> AuthenticatedAthlete:
    """Resolve a session that may still be completing required onboarding."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _authentication_required()
    try:
        return AuthenticationService(database_session).authenticate_onboarding(
            credentials.credentials
        )
    except AuthenticationRejectedError as error:
        raise _authentication_required() from error
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from error


OnboardingAthleteDependency = Annotated[
    AuthenticatedAthlete,
    Depends(onboarding_athlete),
]


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegistrationRequest,
    database_session: DatabaseSessionDependency,
) -> LoginResponse:
    """Create a pending account that must upload a Strava history ZIP."""

    try:
        registered = NewAthleteRegistrationService(database_session).register(
            NewAthleteRegistration(
                display_name=body.display_name,
                email=body.email,
                password=body.password.get_secret_value(),
                timezone=body.timezone,
                goal_distance=body.goal_distance,
                race_date=body.race_date,
                target_time_seconds=body.target_time_seconds,
                days_per_week=body.days_per_week,
                benchmark_distance=body.benchmark_distance,
                benchmark_elapsed_time_ms=round(body.benchmark_elapsed_time_seconds * 1_000),
                benchmark_date=body.benchmark_date,
                benchmark_label=body.benchmark_label,
                research_consent=body.research_consent,
            )
        )
    except IdentityConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already uses that email address.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration service is unavailable.",
        ) from error

    return LoginResponse(
        access_token=registered.access_token,
        token_type="bearer",
        expires_at=registered.identity.expires_at,
        athlete=_athlete_response(registered.identity),
    )


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    database_session: DatabaseSessionDependency,
) -> LoginResponse:
    """Verify credentials and issue one revocable opaque bearer session."""

    try:
        issued = AuthenticationService(database_session).login(
            email=body.email,
            password=body.password.get_secret_value(),
        )
    except AuthenticationRejectedError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from error

    return LoginResponse(
        access_token=issued.access_token,
        token_type="bearer",
        expires_at=issued.identity.expires_at,
        athlete=_athlete_response(issued.identity),
    )


@router.get("/me", response_model=CurrentAccountResponse)
def current_account(identity: AuthenticatedAthleteDependency) -> CurrentAccountResponse:
    """Return the athlete display context owned by the bearer session."""

    return CurrentAccountResponse(
        athlete=_athlete_response(identity),
        session_expires_at=identity.expires_at,
    )


@router.get("/onboarding", response_model=CurrentAccountResponse)
def onboarding_account(identity: OnboardingAthleteDependency) -> CurrentAccountResponse:
    """Return account state while required Strava onboarding is pending."""

    return CurrentAccountResponse(
        athlete=_athlete_response(identity),
        session_expires_at=identity.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: BearerCredentialsDependency,
    identity: OnboardingAthleteDependency,
    database_session: DatabaseSessionDependency,
) -> Response:
    """Revoke the current bearer session."""

    del identity
    if credentials is None:
        raise _authentication_required()
    try:
        AuthenticationService(database_session).logout(credentials.credentials)
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable.",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
