"""Core persistence models for ingestion and canonical activities."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from runcoach.db.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class TimestampMixin:
    """Database-managed creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Athlete(TimestampMixin, Base):
    """A stable athlete identity referenced by athlete-owned records."""

    __tablename__ = "athletes"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)


class UserAccount(TimestampMixin, Base):
    """A login identity mapped one-to-one to an athlete domain identity."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_onboarding', 'active', 'disabled')",
            name="user_accounts_status",
        ),
        UniqueConstraint("athlete_id", name="uq_user_accounts_athlete"),
        UniqueConstraint("email_normalized", name="uq_user_accounts_email"),
        Index("ix_user_accounts_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'pending_onboarding'"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AuthSession(Base):
    """One revocable opaque login session; only the token hash is persisted."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="auth_sessions_expiry",
        ),
        CheckConstraint(
            "last_seen_at >= created_at",
            name="auth_sessions_last_seen",
        ),
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_account_expires", "user_account_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AthleteOnboarding(TimestampMixin, Base):
    """Durable progress through required Strava-history onboarding."""

    __tablename__ = "athlete_onboarding"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'awaiting_strava_archive', 'validating_archive', 'importing_history', "
            "'calculating_analytics', 'generating_plan', 'ready', 'failed'"
            ")",
            name="athlete_onboarding_status",
        ),
        CheckConstraint(
            "status <> 'ready' OR ("
            "strava_import_batch_id IS NOT NULL AND goal_id IS NOT NULL "
            "AND training_plan_id IS NOT NULL"
            ")",
            name="athlete_onboarding_ready",
        ),
        CheckConstraint(
            "status <> 'failed' OR failure_code IS NOT NULL",
            name="athlete_onboarding_failure",
        ),
        Index("ix_athlete_onboarding_status", "status"),
    )

    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'awaiting_strava_archive'"),
    )
    strava_import_batch_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    goal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
    )
    training_plan_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ResearchConsent(Base):
    """Append-only consent decision for cross-athlete model research."""

    __tablename__ = "research_consents"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('granted', 'withdrawn')",
            name="research_consents_decision",
        ),
        Index("ix_research_consents_athlete_recorded", "athlete_id", "recorded_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ImportBatch(Base):
    """One durable and auditable execution of the ingestion pipeline."""

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'completed_with_warnings', 'failed')",
            name="import_batches_status",
        ),
        CheckConstraint("retry_count >= 0", name="import_batches_retry_count"),
        CheckConstraint("total_files >= 0", name="import_batches_total_files"),
        CheckConstraint(
            "accepted_files >= 0",
            name="import_batches_accepted_files",
        ),
        CheckConstraint(
            "rejected_files >= 0",
            name="import_batches_rejected_files",
        ),
        CheckConstraint(
            "duplicate_files >= 0",
            name="import_batches_duplicate_files",
        ),
        CheckConstraint(
            "warning_count >= 0",
            name="import_batches_warning_count",
        ),
        Index("ix_import_batches_athlete_requested", "athlete_id", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'pending'"),
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    parser_bundle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    total_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    accepted_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    rejected_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    duplicate_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    warning_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    sanitized_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ImportFile(Base):
    """File identity and processing metadata without storing file bytes."""

    __tablename__ = "import_files"
    __table_args__ = (
        CheckConstraint(
            "source_provider IN ('garmin', 'strava', 'unknown')",
            name="import_files_source_provider",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'duplicate', 'failed', 'deleted')",
            name="import_files_status",
        ),
        CheckConstraint("size_bytes >= 0", name="import_files_size"),
        Index("ix_import_files_batch", "import_batch_id"),
        Index("ix_import_files_sha256", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    import_batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    detected_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Activity(TimestampMixin, Base):
    """A canonical athlete activity resolved from provider records."""

    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "activity_type IN ('race', 'workout', 'easy', 'long', 'unknown', 'other')",
            name="activities_type",
        ),
        CheckConstraint("distance_m >= 0", name="activities_distance"),
        CheckConstraint("moving_time_ms >= 0", name="activities_moving_time"),
        CheckConstraint("elapsed_time_ms >= 0", name="activities_elapsed_time"),
        CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'excluded')",
            name="activities_verification_status",
        ),
        Index(
            "ix_activities_duplicate_candidates",
            "athlete_id",
            "sport",
            "start_time_utc",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sport: Mapped[str] = mapped_column(String(32), nullable=False)
    activity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'unknown'"),
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    original_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    distance_m: Mapped[Decimal] = mapped_column(
        Numeric(12, 3),
        nullable=False,
    )
    moving_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    elapsed_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    elevation_gain_m: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    average_hr_bpm: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )
    max_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    average_cadence_spm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    calories_kcal: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    canonical_sensor_source_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "source_activities.id",
            name="fk_activities_canonical_sensor_source_id_source_activities",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'unverified'"),
    )


class SourceActivity(Base):
    """A provider-specific activity record used for canonical resolution."""

    __tablename__ = "source_activities"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('garmin', 'strava', 'unknown')",
            name="source_activities_provider",
        ),
        CheckConstraint(
            "source_distance_m IS NULL OR source_distance_m >= 0",
            name="source_activities_distance",
        ),
        CheckConstraint(
            "source_duration_ms IS NULL OR source_duration_ms >= 0",
            name="source_activities_duration",
        ),
        CheckConstraint(
            "resolution_status IN ('unresolved', 'canonical', 'duplicate', 'review')",
            name="source_activities_resolution_status",
        ),
        UniqueConstraint(
            "provider",
            "external_activity_id",
            name="uq_source_activities_provider_external",
        ),
        Index("ix_source_activities_import_file", "import_file_id"),
        Index("ix_source_activities_activity", "activity_id"),
        Index("ix_source_activities_dedupe", "dedupe_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    import_file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_activity_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    source_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_sport: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_distance_m: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )
    source_duration_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    dedupe_fingerprint: Mapped[str | None] = mapped_column(
        CHAR(64),
        nullable=True,
    )
    resolution_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'unresolved'"),
    )
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SourceActivityFile(Base):
    """Associate a provider activity with each contributing import file."""

    __tablename__ = "source_activity_files"
    __table_args__ = (
        CheckConstraint(
            "file_role IN ('summary', 'sensor', 'route', 'attachment')",
            name="source_activity_files_role",
        ),
        UniqueConstraint(
            "source_activity_id",
            "import_file_id",
            name="uq_source_activity_files_source_file",
        ),
        Index("ix_source_activity_files_import_file", "import_file_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    import_file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Lap(Base):
    """One normalized lap belonging to a canonical activity."""

    __tablename__ = "laps"
    __table_args__ = (
        CheckConstraint("lap_index >= 0", name="laps_index"),
        CheckConstraint(
            "distance_m IS NULL OR distance_m >= 0",
            name="laps_distance",
        ),
        CheckConstraint(
            "moving_time_ms IS NULL OR moving_time_ms >= 0",
            name="laps_moving_time",
        ),
        CheckConstraint(
            "elapsed_time_ms IS NULL OR elapsed_time_ms >= 0",
            name="laps_elapsed_time",
        ),
        UniqueConstraint(
            "activity_id",
            "lap_index",
            name="uq_laps_activity_index",
        ),
        Index("ix_laps_activity", "activity_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    distance_m: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )
    moving_time_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    elapsed_time_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    elevation_gain_m: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    average_hr_bpm: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )
    max_hr_bpm: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    average_cadence_spm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )


class Trackpoint(Base):
    """One ordered sensor observation selected for a canonical activity."""

    __tablename__ = "trackpoints"
    __table_args__ = (
        CheckConstraint(
            "sequence_number >= 0",
            name="trackpoints_sequence_number",
        ),
        CheckConstraint("elapsed_ms >= 0", name="trackpoints_elapsed"),
        Index(
            "ix_trackpoints_activity_recorded",
            "activity_id",
            "recorded_at",
        ),
    )

    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    distance_m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3),
        nullable=True,
    )
    latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6),
        nullable=True,
    )
    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6),
        nullable=True,
    )
    altitude_m: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    heart_rate_bpm: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    cadence_spm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    speed_mps: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    power_watts: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    temperature_c: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )
    is_paused: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )


class ActivityFieldSource(Base):
    """Field-level provenance for a selected canonical value."""

    __tablename__ = "activity_field_sources"
    __table_args__ = (
        UniqueConstraint(
            "activity_id",
            "field_name",
            name="uq_activity_field_sources_activity_field",
        ),
        Index("ix_activity_field_sources_source", "source_activity_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    selection_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DataQualityIssue(Base):
    """A structured, reviewable data-quality finding."""

    __tablename__ = "data_quality_issues"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'error', 'blocking')",
            name="data_quality_issues_severity",
        ),
        CheckConstraint(
            "resolution_status IN ('open', 'accepted', 'corrected', 'dismissed')",
            name="data_quality_issues_resolution_status",
        ),
        CheckConstraint(
            "import_batch_id IS NOT NULL "
            "OR source_activity_id IS NOT NULL "
            "OR activity_id IS NOT NULL",
            name="data_quality_issues_scope",
        ),
        Index("ix_data_quality_issues_batch", "import_batch_id"),
        Index("ix_data_quality_issues_source", "source_activity_id"),
        Index("ix_data_quality_issues_activity", "activity_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    import_batch_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[Any | None] = mapped_column(
        JSON_DOCUMENT,
        nullable=True,
    )
    resolution_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'open'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PhysiologyProfile(Base):
    """Time-valid athlete physiology inputs used by deterministic metrics."""

    __tablename__ = "physiology_profiles"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="physiology_profiles_valid_period",
        ),
        CheckConstraint(
            "observed_max_hr_bpm IS NULL OR observed_max_hr_bpm BETWEEN 100 AND 250",
            name="physiology_profiles_max_hr",
        ),
        CheckConstraint(
            "resting_hr_bpm IS NULL OR resting_hr_bpm BETWEEN 25 AND 120",
            name="physiology_profiles_resting_hr",
        ),
        CheckConstraint(
            "lactate_threshold_hr_bpm IS NULL OR lactate_threshold_hr_bpm BETWEEN 80 AND 230",
            name="physiology_profiles_threshold_hr",
        ),
        CheckConstraint(
            "threshold_pace_seconds_per_km IS NULL OR threshold_pace_seconds_per_km > 0",
            name="physiology_profiles_threshold_pace",
        ),
        UniqueConstraint(
            "athlete_id",
            "valid_from",
            name="uq_physiology_profiles_athlete_valid_from",
        ),
        Index(
            "ix_physiology_profiles_athlete_period",
            "athlete_id",
            "valid_from",
            "valid_to",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_max_hr_bpm: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    resting_hr_bpm: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    lactate_threshold_hr_bpm: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )
    threshold_pace_seconds_per_km: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    zone_method: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ActivityMetric(Base):
    """One versioned deterministic metric result for an activity."""

    __tablename__ = "activity_metrics"
    __table_args__ = (
        CheckConstraint(
            "heart_rate_coverage_pct BETWEEN 0 AND 100",
            name="activity_metrics_hr_coverage",
        ),
        CheckConstraint(
            "gps_coverage_pct BETWEEN 0 AND 100",
            name="activity_metrics_gps_coverage",
        ),
        CheckConstraint(
            "cadence_coverage_pct BETWEEN 0 AND 100",
            name="activity_metrics_cadence_coverage",
        ),
        CheckConstraint(
            "training_load IS NULL OR training_load >= 0",
            name="activity_metrics_training_load",
        ),
        CheckConstraint(
            "length(input_hash) = 64",
            name="activity_metrics_input_hash",
        ),
        UniqueConstraint(
            "activity_id",
            "algorithm_version",
            "input_hash",
            name="uq_activity_metrics_activity_version_input",
        ),
        Index(
            "ix_activity_metrics_activity_calculated",
            "activity_id",
            "calculated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    profile_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("physiology_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    average_pace_seconds_per_km: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    heart_rate_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3),
        nullable=False,
    )
    gps_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3),
        nullable=False,
    )
    cadence_coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3),
        nullable=False,
    )
    load_method: Mapped[str] = mapped_column(String(64), nullable=False)
    training_load: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    zone_distribution: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )
    additional_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
        default=dict,
    )


class DailyLoad(Base):
    """One versioned daily workload and fitness-fatigue state."""

    __tablename__ = "daily_loads"
    __table_args__ = (
        CheckConstraint(
            "daily_load >= 0",
            name="daily_loads_daily_load",
        ),
        CheckConstraint(
            "acute_load IS NULL OR acute_load >= 0",
            name="daily_loads_acute_load",
        ),
        CheckConstraint(
            "chronic_load IS NULL OR chronic_load >= 0",
            name="daily_loads_chronic_load",
        ),
        CheckConstraint(
            "fitness_index IS NULL OR fitness_index >= 0",
            name="daily_loads_fitness_index",
        ),
        CheckConstraint(
            "fatigue_index IS NULL OR fatigue_index >= 0",
            name="daily_loads_fatigue_index",
        ),
        CheckConstraint(
            "coverage_pct BETWEEN 0 AND 100",
            name="daily_loads_coverage",
        ),
        UniqueConstraint(
            "athlete_id",
            "local_date",
            "load_method",
            "algorithm_version",
            name="uq_daily_loads_athlete_date_method_version",
        ),
        Index(
            "ix_daily_loads_athlete_date",
            "athlete_id",
            "local_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    load_method: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    daily_load: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
    )
    acute_load: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    chronic_load: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    fitness_index: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    fatigue_index: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    form_index: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    coverage_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 3),
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PersonalBest(Base):
    """One verified standard-distance personal-best progression event."""

    __tablename__ = "personal_bests"
    __table_args__ = (
        CheckConstraint(
            "distance_m IN (5000, 10000, 21097.5, 42195)",
            name="personal_bests_standard_distance",
        ),
        CheckConstraint(
            "elapsed_time_ms > 0",
            name="personal_bests_elapsed_time",
        ),
        CheckConstraint(
            "effort_type IN "
            "('whole_activity', 'distance_interpolation', "
            "'rolling_segment', 'provider_best_effort')",
            name="personal_bests_effort_type",
        ),
        CheckConstraint(
            "verification_status IN "
            "('verified_race', 'verified_time_trial', 'verified_max_effort')",
            name="personal_bests_verification_status",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= achieved_at",
            name="personal_bests_superseded_after_achievement",
        ),
        UniqueConstraint(
            "activity_id",
            "distance_m",
            "elapsed_time_ms",
            "verification_status",
            "verification_source",
            name="uq_personal_bests_evidence",
        ),
        Index(
            "ix_personal_bests_athlete_distance_achieved",
            "athlete_id",
            "distance_m",
            "achieved_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    activity_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    distance_m: Mapped[Decimal] = mapped_column(
        Numeric(10, 3),
        nullable=False,
    )
    elapsed_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    effort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_source: Mapped[str] = mapped_column(String(64), nullable=False)
    achieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Goal(TimestampMixin, Base):
    """A durable athlete race goal that owns versioned training plans."""

    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint(
            "race_type IN ('5k', '10k', 'half_marathon', 'marathon')",
            name="goals_race_type",
        ),
        CheckConstraint(
            "target_time_seconds IS NULL OR target_time_seconds > 0",
            name="goals_target_time",
        ),
        CheckConstraint(
            "days_per_week BETWEEN 3 AND 7",
            name="goals_days_per_week",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'cancelled')",
            name="goals_status",
        ),
        CheckConstraint(
            "priority IN ('primary', 'secondary', 'other')",
            name="goals_priority",
        ),
        UniqueConstraint(
            "athlete_id",
            "race_type",
            "race_date",
            name="uq_goals_athlete_race_date",
        ),
        Index("ix_goals_athlete_status", "athlete_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    race_type: Mapped[str] = mapped_column(String(32), nullable=False)
    race_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_time_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    days_per_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'planned'"),
    )
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'primary'"),
    )


class TrainingPlan(Base):
    """An immutable generated plan snapshot for one durable race goal."""

    __tablename__ = "training_plans"
    __table_args__ = (
        CheckConstraint("version > 0", name="training_plans_version"),
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="training_plans_status",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64",
            name="training_plans_evidence_hash",
        ),
        UniqueConstraint(
            "goal_id",
            "version",
            name="uq_training_plans_goal_version",
        ),
        UniqueConstraint(
            "goal_id",
            "evidence_hash",
            name="uq_training_plans_goal_evidence",
        ),
        Index("ix_training_plans_goal_status", "goal_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    goal_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CoachingRun(Base):
    """One completed execution of the evidence-grounded coaching workflow."""

    __tablename__ = "coaching_runs"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('disabled', 'openai', 'fake')",
            name="coaching_runs_provider",
        ),
        CheckConstraint(
            "status IN ('running', 'approved', 'fallback', 'failed')",
            name="coaching_runs_status",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="coaching_runs_completion",
        ),
        Index("ix_coaching_runs_athlete_started", "athlete_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    athlete_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("athletes.id", ondelete="CASCADE"),
        nullable=False,
    )
    goal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
    )
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AgentStep(Base):
    """One ordered and minimized decision in a persisted coaching run."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        CheckConstraint("sequence_number > 0", name="agent_steps_sequence"),
        CheckConstraint(
            "decision IN ('continue', 'block', 'revise', 'approve', 'fallback')",
            name="agent_steps_decision",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="agent_steps_completion",
        ),
        UniqueConstraint(
            "coaching_run_id",
            "sequence_number",
            name="uq_agent_steps_run_sequence",
        ),
        Index("ix_agent_steps_coaching_run", "coaching_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    coaching_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("coaching_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_evidence_refs: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Recommendation(Base):
    """Approved or deterministic-fallback recommendation from one coaching run."""

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint(
            "confidence IN ('not_scored', 'low', 'medium', 'high')",
            name="recommendations_confidence",
        ),
        CheckConstraint(
            "review_status IN ('approved', 'fallback')",
            name="recommendations_review_status",
        ),
        UniqueConstraint("coaching_run_id", name="uq_recommendations_coaching_run"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    coaching_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("coaching_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
