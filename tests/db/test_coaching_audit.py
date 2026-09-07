"""Tests for durable minimized coaching-run audit records."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from runcoach.coaching.chat import CoachingReply
from runcoach.db.base import Base
from runcoach.db.coaching_audit import (
    COACHING_GRAPH_VERSION,
    CoachingAuditPersistenceError,
    CoachingAuditPersistenceService,
)
from runcoach.db.models import AgentStep, Athlete, CoachingRun, Goal, Recommendation

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            Athlete(
                id=ATHLETE_ID,
                display_name="Synthetic Athlete",
                timezone="Africa/Casablanca",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _reply(*, mode: Literal["openai", "deterministic"] = "deterministic") -> CoachingReply:
    return CoachingReply(
        answer="Keep tomorrow's recovery run conversational at the prescribed easy pace.",
        evidence_ids=("plan:next-session:1", "plan:tracking"),
        limitations=("Sleep and soreness are not represented.",),
        mode=mode,
        model="gpt-test" if mode == "openai" else None,
        context_version="coaching_context_v2",
        prompt_version="evidence_coach_v2",
    )


def _active_goal(session: Session, *, race_date: date = date(2027, 1, 31)) -> Goal:
    goal = Goal(
        athlete_id=ATHLETE_ID,
        race_type="marathon",
        race_date=race_date,
        target_time_seconds=11_400,
        days_per_week=6,
        status="active",
        priority="primary",
    )
    session.add(goal)
    session.commit()
    return goal


def test_coaching_audit_tables_are_registered_with_expected_ownership() -> None:
    assert {"coaching_runs", "agent_steps", "recommendations"} <= set(Base.metadata.tables)
    assert next(iter(CoachingRun.__table__.c.athlete_id.foreign_keys)).target_fullname == (
        "athletes.id"
    )
    assert next(iter(AgentStep.__table__.c.coaching_run_id.foreign_keys)).target_fullname == (
        "coaching_runs.id"
    )
    assert (
        next(iter(Recommendation.__table__.c.coaching_run_id.foreign_keys)).target_fullname
        == "coaching_runs.id"
    )


def test_persist_completed_records_minimized_fallback_workflow(db_session: Session) -> None:
    goal = _active_goal(db_session)
    started_at = datetime(2026, 9, 7, 8, tzinfo=UTC)
    question = "What pace should tomorrow's recovery run be?"

    result = CoachingAuditPersistenceService(db_session).persist_completed(
        athlete_id=ATHLETE_ID,
        question=question,
        conversation_turns=2,
        reply=_reply(),
        provider="disabled",
        started_at=started_at,
        completed_at=started_at + timedelta(milliseconds=250),
    )

    coaching_run = db_session.get(CoachingRun, result.coaching_run_id)
    assert coaching_run is not None
    assert coaching_run.goal_id == goal.id
    assert coaching_run.graph_version == COACHING_GRAPH_VERSION
    assert coaching_run.provider == "disabled"
    assert coaching_run.status == "fallback"
    assert coaching_run.state["question_length"] == len(question)
    assert len(str(coaching_run.state["question_sha256"])) == 64
    assert question not in json.dumps(coaching_run.state)

    steps = tuple(
        db_session.scalars(
            select(AgentStep)
            .where(AgentStep.coaching_run_id == coaching_run.id)
            .order_by(AgentStep.sequence_number)
        )
    )
    assert [step.agent_name for step in steps] == [
        "evidence_context",
        "answer_generation",
        "safety_review",
    ]
    assert [step.decision for step in steps] == ["continue", "fallback", "fallback"]

    recommendation = db_session.scalar(
        select(Recommendation).where(Recommendation.coaching_run_id == coaching_run.id)
    )
    assert recommendation is not None
    assert recommendation.id == result.recommendation_id
    assert recommendation.evidence_refs == ["plan:next-session:1", "plan:tracking"]
    assert recommendation.warnings == ["Sleep and soreness are not represented."]
    assert recommendation.review_status == "fallback"


def test_openai_reply_is_persisted_as_approved(db_session: Session) -> None:
    started_at = datetime(2026, 9, 7, 8, tzinfo=UTC)

    result = CoachingAuditPersistenceService(db_session).persist_completed(
        athlete_id=ATHLETE_ID,
        question="How is my marathon preparation?",
        conversation_turns=0,
        reply=_reply(mode="openai"),
        provider="openai",
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
    )

    assert result.status == "approved"
    assert db_session.scalar(select(func.count()).select_from(CoachingRun)) == 1
    recommendation = db_session.scalar(select(Recommendation))
    assert recommendation is not None
    assert recommendation.review_status == "approved"


def test_multiple_active_primary_goals_are_rejected(db_session: Session) -> None:
    _active_goal(db_session)
    db_session.add(
        Goal(
            athlete_id=ATHLETE_ID,
            race_type="half_marathon",
            race_date=date(2027, 3, 1),
            target_time_seconds=None,
            days_per_week=5,
            status="active",
            priority="primary",
        )
    )
    db_session.commit()

    with pytest.raises(CoachingAuditPersistenceError, match="Multiple active primary goals"):
        CoachingAuditPersistenceService(db_session).persist_completed(
            athlete_id=ATHLETE_ID,
            question="What is next?",
            conversation_turns=0,
            reply=_reply(),
            provider="disabled",
            started_at=datetime(2026, 9, 7, 8, tzinfo=UTC),
        )

    assert db_session.scalar(select(func.count()).select_from(CoachingRun)) == 0
