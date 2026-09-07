"""add coaching run audit

Revision ID: e7b3c1d9a4f2
Revises: 8f2c7149a6d0
Created: 2026-09-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3c1d9a4f2"
down_revision: str | Sequence[str] | None = "8f2c7149a6d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create minimized coaching-run, step, and recommendation audit tables."""

    op.create_table(
        "coaching_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="coaching_runs_completion",
        ),
        sa.CheckConstraint(
            "provider IN ('disabled', 'openai', 'fake')",
            name="coaching_runs_provider",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'approved', 'fallback', 'failed')",
            name="coaching_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_coaching_runs_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["goals.id"],
            name=op.f("fk_coaching_runs_goal_id_goals"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coaching_runs")),
    )
    op.create_index(
        "ix_coaching_runs_athlete_started",
        "coaching_runs",
        ["athlete_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("coaching_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column(
            "input_evidence_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="agent_steps_completion",
        ),
        sa.CheckConstraint(
            "decision IN ('continue', 'block', 'revise', 'approve', 'fallback')",
            name="agent_steps_decision",
        ),
        sa.CheckConstraint("sequence_number > 0", name="agent_steps_sequence"),
        sa.ForeignKeyConstraint(
            ["coaching_run_id"],
            ["coaching_runs.id"],
            name=op.f("fk_agent_steps_coaching_run_id_coaching_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
        sa.UniqueConstraint(
            "coaching_run_id",
            "sequence_number",
            name="uq_agent_steps_run_sequence",
        ),
    )
    op.create_index(
        "ix_agent_steps_coaching_run",
        "agent_steps",
        ["coaching_run_id"],
        unique=False,
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("coaching_run_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IN ('not_scored', 'low', 'medium', 'high')",
            name="recommendations_confidence",
        ),
        sa.CheckConstraint(
            "review_status IN ('approved', 'fallback')",
            name="recommendations_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["coaching_run_id"],
            ["coaching_runs.id"],
            name=op.f("fk_recommendations_coaching_run_id_coaching_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint("coaching_run_id", name="uq_recommendations_coaching_run"),
    )


def downgrade() -> None:
    """Remove coaching audit tables in dependency order."""

    op.drop_table("recommendations")
    op.drop_index("ix_agent_steps_coaching_run", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_coaching_runs_athlete_started", table_name="coaching_runs")
    op.drop_table("coaching_runs")
