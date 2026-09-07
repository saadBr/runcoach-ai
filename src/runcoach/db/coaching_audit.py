"""Durable audit persistence for completed conversational coaching runs."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from runcoach.coaching.chat import CoachingReply
from runcoach.db.models import AgentStep, CoachingRun, Goal, Recommendation

COACHING_GRAPH_VERSION = "evidence_coaching_workflow_v1"
type CoachingProvider = Literal["disabled", "openai", "fake"]


class CoachingAuditPersistenceError(RuntimeError):
    """Raised when a completed coaching run cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class PersistedCoachingAudit:
    """Identifiers and terminal status for one persisted coaching run."""

    coaching_run_id: UUID
    recommendation_id: UUID
    status: Literal["approved", "fallback"]


class CoachingAuditPersistenceService:
    """Persist minimized workflow state, ordered steps, and the final recommendation."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _active_goal_id(self, athlete_id: UUID) -> UUID | None:
        goal_ids = tuple(
            self._session.scalars(
                select(Goal.id).where(
                    Goal.athlete_id == athlete_id,
                    Goal.status == "active",
                    Goal.priority == "primary",
                )
            ).all()
        )
        if len(goal_ids) > 1:
            raise CoachingAuditPersistenceError(
                "Multiple active primary goals prevent unambiguous coaching audit persistence."
            )
        return goal_ids[0] if goal_ids else None

    def persist_completed(
        self,
        *,
        athlete_id: UUID,
        question: str,
        conversation_turns: int,
        reply: CoachingReply,
        provider: CoachingProvider,
        started_at: datetime,
        completed_at: datetime | None = None,
    ) -> PersistedCoachingAudit:
        """Persist one terminal coaching run without retaining the raw question."""

        normalized_question = question.strip()
        finished_at = completed_at or datetime.now(UTC)
        if not normalized_question:
            raise CoachingAuditPersistenceError("A coaching audit requires a non-empty question.")
        if conversation_turns < 0:
            raise CoachingAuditPersistenceError("Conversation turn count cannot be negative.")
        if started_at.tzinfo is None or finished_at.tzinfo is None:
            raise CoachingAuditPersistenceError("Coaching audit timestamps must include timezone.")
        if finished_at < started_at:
            raise CoachingAuditPersistenceError("Coaching completion cannot precede its start.")

        terminal_status: Literal["approved", "fallback"] = (
            "approved" if reply.mode == "openai" else "fallback"
        )
        evidence_refs = list(reply.evidence_ids)
        try:
            goal_id = self._active_goal_id(athlete_id)
        except SQLAlchemyError as error:
            self._session.rollback()
            raise CoachingAuditPersistenceError(
                "The active goal could not be resolved for coaching audit persistence."
            ) from error
        coaching_run = CoachingRun(
            athlete_id=athlete_id,
            goal_id=goal_id,
            graph_version=COACHING_GRAPH_VERSION,
            provider=provider,
            status=terminal_status,
            state={
                "question_sha256": sha256(normalized_question.encode("utf-8")).hexdigest(),
                "question_length": len(normalized_question),
                "conversation_turns": conversation_turns,
                "reply_mode": reply.mode,
                "context_version": reply.context_version,
                "prompt_version": reply.prompt_version,
                "evidence_ids": evidence_refs,
                "limitation_count": len(reply.limitations),
            },
            started_at=started_at,
            completed_at=finished_at,
        )
        try:
            self._session.add(coaching_run)
            self._session.flush()
            steps = (
                AgentStep(
                    coaching_run_id=coaching_run.id,
                    sequence_number=1,
                    agent_name="evidence_context",
                    input_evidence_refs=[],
                    output={
                        "context_version": reply.context_version,
                        "evidence_count": len(evidence_refs),
                    },
                    decision="continue",
                    provider_request_id=None,
                    token_usage=None,
                    started_at=started_at,
                    completed_at=finished_at,
                ),
                AgentStep(
                    coaching_run_id=coaching_run.id,
                    sequence_number=2,
                    agent_name="answer_generation",
                    input_evidence_refs=evidence_refs,
                    output={
                        "mode": reply.mode,
                        "model": reply.model,
                        "prompt_version": reply.prompt_version,
                    },
                    decision="continue" if reply.mode == "openai" else "fallback",
                    provider_request_id=None,
                    token_usage=None,
                    started_at=started_at,
                    completed_at=finished_at,
                ),
                AgentStep(
                    coaching_run_id=coaching_run.id,
                    sequence_number=3,
                    agent_name="safety_review",
                    input_evidence_refs=evidence_refs,
                    output={
                        "evidence_count": len(evidence_refs),
                        "limitation_count": len(reply.limitations),
                    },
                    decision="approve" if reply.mode == "openai" else "fallback",
                    provider_request_id=None,
                    token_usage=None,
                    started_at=started_at,
                    completed_at=finished_at,
                ),
            )
            recommendation = Recommendation(
                coaching_run_id=coaching_run.id,
                recommendation_type="chat_answer",
                summary=reply.answer,
                rationale=(
                    "The answer is traceable to the persisted evidence references and "
                    "versioned coaching workflow."
                ),
                evidence_refs=evidence_refs,
                confidence="not_scored",
                warnings=list(reply.limitations),
                review_status=terminal_status,
            )
            self._session.add_all((*steps, recommendation))
            self._session.commit()
        except SQLAlchemyError as error:
            self._session.rollback()
            raise CoachingAuditPersistenceError(
                "The completed coaching run could not be persisted."
            ) from error

        return PersistedCoachingAudit(
            coaching_run_id=coaching_run.id,
            recommendation_id=recommendation.id,
            status=terminal_status,
        )
