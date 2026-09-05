"""add versioned training plans

Revision ID: 8f2c7149a6d0
Revises: c1dc53dc2033
Created: 2026-09-05 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8f2c7149a6d0"
down_revision: str | Sequence[str] | None = "c1dc53dc2033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable race goals and immutable plan snapshots."""

    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("race_type", sa.String(length=32), nullable=False),
        sa.Column("race_date", sa.Date(), nullable=False),
        sa.Column("target_time_seconds", sa.BigInteger(), nullable=True),
        sa.Column("days_per_week", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'planned'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.String(length=16),
            server_default=sa.text("'primary'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "race_type IN ('5k', '10k', 'half_marathon', 'marathon')",
            name="goals_race_type",
        ),
        sa.CheckConstraint(
            "target_time_seconds IS NULL OR target_time_seconds > 0",
            name="goals_target_time",
        ),
        sa.CheckConstraint(
            "days_per_week BETWEEN 3 AND 7",
            name="goals_days_per_week",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'cancelled')",
            name="goals_status",
        ),
        sa.CheckConstraint(
            "priority IN ('primary', 'secondary', 'other')",
            name="goals_priority",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_goals_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
        sa.UniqueConstraint(
            "athlete_id",
            "race_type",
            "race_date",
            name="uq_goals_athlete_race_date",
        ),
    )
    op.create_index(
        "ix_goals_athlete_status",
        "goals",
        ["athlete_id", "status"],
        unique=False,
    )
    op.create_table(
        "training_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_as_of_date", sa.Date(), nullable=False),
        sa.Column("evidence_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "plan_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="training_plans_version"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="training_plans_status",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="training_plans_evidence_hash",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["goals.id"],
            name=op.f("fk_training_plans_goal_id_goals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_plans")),
        sa.UniqueConstraint(
            "goal_id",
            "evidence_hash",
            name="uq_training_plans_goal_evidence",
        ),
        sa.UniqueConstraint(
            "goal_id",
            "version",
            name="uq_training_plans_goal_version",
        ),
    )
    op.create_index(
        "ix_training_plans_goal_status",
        "training_plans",
        ["goal_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove durable race goals and generated plans."""

    op.drop_index("ix_training_plans_goal_status", table_name="training_plans")
    op.drop_table("training_plans")
    op.drop_index("ix_goals_athlete_status", table_name="goals")
    op.drop_table("goals")
