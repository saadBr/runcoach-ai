"""add multi-athlete onboarding foundation

Revision ID: d4f6a2c8b901
Revises: e7b3c1d9a4f2
Created: 2026-09-07 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f6a2c8b901"
down_revision: str | Sequence[str] | None = "e7b3c1d9a4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create account, session, onboarding, and research-consent tables."""

    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending_onboarding'"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending_onboarding', 'active', 'disabled')",
            name="user_accounts_status",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_user_accounts_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_accounts")),
        sa.UniqueConstraint("athlete_id", name="uq_user_accounts_athlete"),
        sa.UniqueConstraint("email_normalized", name="uq_user_accounts_email"),
    )
    op.create_index(
        "ix_user_accounts_status",
        "user_accounts",
        ["status"],
        unique=False,
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="auth_sessions_expiry"),
        sa.CheckConstraint("last_seen_at >= created_at", name="auth_sessions_last_seen"),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name=op.f("fk_auth_sessions_user_account_id_user_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_account_expires",
        "auth_sessions",
        ["user_account_id", "expires_at"],
        unique=False,
    )
    op.create_table(
        "research_consents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('granted', 'withdrawn')",
            name="research_consents_decision",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_research_consents_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_consents")),
    )
    op.create_index(
        "ix_research_consents_athlete_recorded",
        "research_consents",
        ["athlete_id", "recorded_at"],
        unique=False,
    )
    op.create_table(
        "athlete_onboarding",
        sa.Column("athlete_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'awaiting_strava_archive'"),
            nullable=False,
        ),
        sa.Column("strava_import_batch_id", sa.Uuid(), nullable=True),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("training_plan_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status <> 'failed' OR failure_code IS NOT NULL",
            name="athlete_onboarding_failure",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR ("
            "strava_import_batch_id IS NOT NULL AND goal_id IS NOT NULL "
            "AND training_plan_id IS NOT NULL"
            ")",
            name="athlete_onboarding_ready",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'awaiting_strava_archive', 'validating_archive', 'importing_history', "
            "'calculating_analytics', 'generating_plan', 'ready', 'failed'"
            ")",
            name="athlete_onboarding_status",
        ),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
            name=op.f("fk_athlete_onboarding_athlete_id_athletes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["goals.id"],
            name=op.f("fk_athlete_onboarding_goal_id_goals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strava_import_batch_id"],
            ["import_batches.id"],
            name=op.f("fk_athlete_onboarding_strava_import_batch_id_import_batches"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["training_plan_id"],
            ["training_plans.id"],
            name=op.f("fk_athlete_onboarding_training_plan_id_training_plans"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("athlete_id", name=op.f("pk_athlete_onboarding")),
    )
    op.create_index(
        "ix_athlete_onboarding_status",
        "athlete_onboarding",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Remove multi-athlete onboarding foundation tables in dependency order."""

    op.drop_index("ix_athlete_onboarding_status", table_name="athlete_onboarding")
    op.drop_table("athlete_onboarding")
    op.drop_index(
        "ix_research_consents_athlete_recorded",
        table_name="research_consents",
    )
    op.drop_table("research_consents")
    op.drop_index("ix_auth_sessions_account_expires", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_user_accounts_status", table_name="user_accounts")
    op.drop_table("user_accounts")
