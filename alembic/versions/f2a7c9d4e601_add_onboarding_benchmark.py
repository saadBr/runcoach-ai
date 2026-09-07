"""add onboarding benchmark

Revision ID: f2a7c9d4e601
Revises: d4f6a2c8b901
Created: 2026-09-07 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a7c9d4e601"
down_revision: str | Sequence[str] | None = "d4f6a2c8b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the declared performance that anchors a new athlete's first plan."""

    op.add_column(
        "athlete_onboarding",
        sa.Column("benchmark_distance", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "athlete_onboarding",
        sa.Column("benchmark_elapsed_time_ms", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "athlete_onboarding",
        sa.Column("benchmark_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "athlete_onboarding",
        sa.Column("benchmark_label", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "athlete_onboarding_benchmark_distance",
        "athlete_onboarding",
        "benchmark_distance IS NULL OR benchmark_distance IN "
        "('5k', '10k', 'half_marathon', 'marathon')",
    )
    op.create_check_constraint(
        "athlete_onboarding_benchmark_time",
        "athlete_onboarding",
        "benchmark_elapsed_time_ms IS NULL OR benchmark_elapsed_time_ms > 0",
    )
    op.create_check_constraint(
        "athlete_onboarding_benchmark_label",
        "athlete_onboarding",
        "benchmark_label IS NULL OR benchmark_label IN "
        "('verified_race', 'verified_time_trial', 'verified_max_effort')",
    )


def downgrade() -> None:
    """Remove onboarding benchmark fields in dependency order."""

    op.drop_constraint(
        "athlete_onboarding_benchmark_label",
        "athlete_onboarding",
        type_="check",
    )
    op.drop_constraint(
        "athlete_onboarding_benchmark_time",
        "athlete_onboarding",
        type_="check",
    )
    op.drop_constraint(
        "athlete_onboarding_benchmark_distance",
        "athlete_onboarding",
        type_="check",
    )
    op.drop_column("athlete_onboarding", "benchmark_label")
    op.drop_column("athlete_onboarding", "benchmark_date")
    op.drop_column("athlete_onboarding", "benchmark_elapsed_time_ms")
    op.drop_column("athlete_onboarding", "benchmark_distance")
