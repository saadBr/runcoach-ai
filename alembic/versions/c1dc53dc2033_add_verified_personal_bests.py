"""add verified personal bests

Revision ID: c1dc53dc2033
Revises: b21e5b4d8e3e
Created: 2026-09-02 16:59:08.304217
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1dc53dc2033"
down_revision: str | Sequence[str] | None = "b21e5b4d8e3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this migration."""

    op.create_table(
        "personal_bests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("distance_m", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("elapsed_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("effort_type", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("verification_source", sa.String(length=64), nullable=False),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effort_type IN "
            "('whole_activity', 'distance_interpolation', "
            "'rolling_segment', 'provider_best_effort')",
            name="personal_bests_effort_type",
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('verified_race', 'verified_time_trial', "
            "'verified_max_effort')",
            name="personal_bests_verification_status",
        ),
        sa.CheckConstraint(
            "distance_m IN (5000, 10000, 21097.5, 42195)",
            name="personal_bests_standard_distance",
        ),
        sa.CheckConstraint(
            "elapsed_time_ms > 0",
            name="personal_bests_elapsed_time",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= achieved_at",
            name="personal_bests_superseded_after_achievement",
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            name=op.f("fk_personal_bests_activity_id_activities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_personal_bests_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_bests")),
        sa.UniqueConstraint(
            "activity_id",
            "distance_m",
            "elapsed_time_ms",
            "verification_status",
            "verification_source",
            name="uq_personal_bests_evidence",
        ),
    )
    op.create_index(
        "ix_personal_bests_athlete_distance_achieved",
        "personal_bests",
        ["athlete_id", "distance_m", "achieved_at"],
        unique=False,
    )


def downgrade() -> None:
    """Reverse this migration."""

    op.drop_index(
        "ix_personal_bests_athlete_distance_achieved",
        table_name="personal_bests",
    )
    op.drop_table("personal_bests")
