"""Core persistence models for ingestion and canonical activities."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
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
