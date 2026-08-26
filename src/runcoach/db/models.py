"""Core persistence models for ingestion and canonical activities."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from runcoach.db.base import Base


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
    """One auditable execution of the ingestion pipeline."""

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="import_batches_status",
        ),
        Index("ix_import_batches_athlete_started", "athlete_id", "started_at"),
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
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SourceFile(Base):
    """A content-addressed source file discovered during an import."""

    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('garmin', 'strava')",
            name="source_files_provider",
        ),
        CheckConstraint(
            "parse_status IN ('pending', 'parsed', 'rejected', 'failed')",
            name="source_files_parse_status",
        ),
        CheckConstraint("size_bytes >= 0", name="source_files_size"),
        UniqueConstraint(
            "athlete_id",
            "provider",
            "content_sha256",
            name="uq_source_files_athlete_provider_hash",
        ),
        Index("ix_source_files_import_batch", "import_batch_id"),
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
    import_batch_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("import_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'pending'"),
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Activity(TimestampMixin, Base):
    """A canonical activity reconciled from one or more source records."""

    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "activity_kind IN ('running', 'trail_running', 'treadmill_running', 'other')",
            name="activities_kind",
        ),
        CheckConstraint(
            "distance_m IS NULL OR distance_m >= 0",
            name="activities_distance",
        ),
        CheckConstraint(
            "elapsed_time_s IS NULL OR elapsed_time_s >= 0",
            name="activities_elapsed_time",
        ),
        CheckConstraint(
            "moving_time_s IS NULL OR moving_time_s >= 0",
            name="activities_moving_time",
        ),
        UniqueConstraint(
            "athlete_id",
            "canonical_key",
            name="uq_activities_athlete_canonical_key",
        ),
        Index("ix_activities_athlete_started", "athlete_id", "started_at"),
        Index("ix_activities_athlete_kind", "athlete_id", "activity_kind"),
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
    canonical_key: Mapped[str] = mapped_column(String(64), nullable=False)
    activity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    elapsed_time_s: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )
    moving_time_s: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )
    distance_m: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 3),
        nullable=True,
    )
    elevation_gain_m: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    elevation_loss_m: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    average_speed_mps: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    maximum_speed_mps: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )

    average_heart_rate_bpm: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    maximum_heart_rate_bpm: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    average_cadence_spm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    maximum_cadence_spm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    calories_kcal: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        nullable=True,
    )
    provider_vo2max: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )
    provider_aerobic_training_effect: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    provider_anaerobic_training_effect: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    provider_training_effect_label: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    has_gps: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )


class ActivitySource(Base):
    """A source record that contributed to a canonical activity."""

    __tablename__ = "activity_sources"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('garmin', 'strava')",
            name="activity_sources_provider",
        ),
        UniqueConstraint(
            "source_file_id",
            "source_record_key",
            name="uq_activity_sources_file_record",
        ),
        Index("ix_activity_sources_activity", "activity_id"),
        Index(
            "ix_activity_sources_provider_external",
            "provider",
            "external_activity_id",
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
    source_file_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(128), nullable=False)
    external_activity_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    source_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    matched_by: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
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
        Index("ix_activity_field_sources_source", "activity_source_id"),
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
    activity_source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activity_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    selection_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ValidationFinding(Base):
    """A structured warning or error produced during ingestion."""

    __tablename__ = "validation_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="validation_findings_severity",
        ),
        Index("ix_validation_findings_batch", "import_batch_id"),
        Index("ix_validation_findings_activity", "activity_id"),
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
    source_file_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("source_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
