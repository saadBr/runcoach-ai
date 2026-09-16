"""Tests for privacy-minimized, evidence-grounded conversational coaching."""

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Self, cast
from urllib.request import Request
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from runcoach.analytics.performance import (
    PerformanceLabel,
    StandardDistance,
)
from runcoach.coaching import chat
from runcoach.coaching.chat import (
    COACHING_CONTEXT_VERSION,
    CoachingContext,
    CoachingReply,
    ConversationalCoachService,
    ConversationTurn,
    DatabaseCoachingContextLoader,
    EvidenceItem,
    GeneratedCoachingReply,
    LanguageModelError,
    OpenAIResponsesLanguageModel,
    UrlLibResponsesTransport,
    build_conversational_coach,
)
from runcoach.config import Settings
from runcoach.db.training_plans import TrainingPlanQueryError

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


def _context() -> CoachingContext:
    return CoachingContext(
        context_version=COACHING_CONTEXT_VERSION,
        as_of_date="2026-09-06",
        evidence=(
            EvidenceItem(
                evidence_id="training:history",
                category="training",
                summary="143 runs; 311.9 km in 28 days.",
                facts={
                    "total_runs": 143,
                    "runs_28d": 22,
                    "distance_28d_km": 311.9,
                    "longest_run_84d_km": 28.0,
                },
            ),
            EvidenceItem(
                evidence_id="workload:2026-09-06",
                category="workload",
                summary="Latest form index is 4.2; acute load is 70 and chronic load is 74.2.",
                facts={"form_index": 4.2, "acute_load": 70.0, "chronic_load": 74.2},
            ),
            EvidenceItem(
                evidence_id="fitness:5k",
                category="prediction",
                summary="Experimental 5k race-readiness estimate is 18:03 with high confidence.",
                facts={
                    "distance": "5k",
                    "race_readiness_time": "18:03",
                    "race_readiness_time_seconds": 1_083.0,
                    "race_readiness_pace_seconds_per_km": 216.6,
                    "confidence": "high",
                },
            ),
            EvidenceItem(
                evidence_id="fitness:marathon",
                category="prediction",
                summary=(
                    "Experimental marathon race-readiness estimate is 3:11:01 at 4:32/km, with "
                    "medium confidence."
                ),
                facts={
                    "distance": "marathon",
                    "race_readiness_time": "3:11:01",
                    "race_readiness_time_seconds": 11_461.0,
                    "race_readiness_pace_seconds_per_km": 272.0,
                    "confidence": "medium",
                },
            ),
            EvidenceItem(
                evidence_id="goal:active",
                category="goal",
                summary="Active marathon goal is scheduled for 2027-01-31; target is 3:10:00.",
                facts={
                    "distance": "marathon",
                    "race_date": "2027-01-31",
                    "target_time": "3:10:00",
                    "target_time_seconds": 11_400.0,
                },
            ),
            EvidenceItem(
                evidence_id="plan:tracking",
                category="plan",
                summary="Continue with the next scheduled session.",
                facts={"status": "in_progress", "adherence_pct": 101.0},
            ),
            EvidenceItem(
                evidence_id="plan:latest-session",
                category="session_review",
                summary="Latest run was 12 km at 6:24/km against 10 km easy.",
                facts={
                    "activity_date": "2026-09-07",
                    "planned_kind": "easy",
                    "target_distance_km": 10.0,
                    "actual_distance_km": 12.0,
                    "actual_pace": "6:24/km",
                    "pace_status": "easier_than_planned",
                },
            ),
            EvidenceItem(
                evidence_id="plan:next-session:1",
                category="session",
                summary=("2026-09-07: Easy aerobic run, 8.5 km at 5:20/km to 5:50/km (upcoming)."),
                facts={
                    "scheduled_date": "2026-09-07",
                    "kind": "easy",
                    "target_distance_km": 8.5,
                    "pace_range": "5:20/km to 5:50/km",
                    "faster_seconds_per_km": 320.0,
                    "slower_seconds_per_km": 350.0,
                },
            ),
        ),
        limitations=("Predictions remain experimental.",),
    )


class FakeLoader:
    def load(self, athlete_id: UUID) -> CoachingContext:
        assert athlete_id == ATHLETE_ID
        return _context()


class LatePlanLoader:
    def load(self, athlete_id: UUID) -> CoachingContext:
        assert athlete_id == ATHLETE_ID
        context = _context()
        evidence = tuple(
            item.model_copy(
                update={
                    "summary": (
                        "2026-09-14: Easy aerobic run, 11.2 km at 5:07/km to 5:47/km (upcoming)."
                    ),
                    "facts": {
                        **item.facts,
                        "scheduled_date": "2026-09-14",
                        "target_distance_km": 11.2,
                        "pace_range": "5:07/km to 5:47/km",
                        "faster_seconds_per_km": 307.0,
                        "slower_seconds_per_km": 347.0,
                    },
                }
            )
            if item.evidence_id == "plan:next-session:1"
            else item
            for item in context.evidence
        )
        return context.model_copy(update={"as_of_date": "2026-09-08", "evidence": evidence})


class FakeModel:
    def __init__(self, reply: GeneratedCoachingReply | Exception) -> None:
        self.reply = reply
        self.conversation: tuple[ConversationTurn, ...] = ()

    @property
    def model_name(self) -> str:
        return "test-model"

    def generate(
        self,
        *,
        question: str,
        conversation: tuple[ConversationTurn, ...],
        context: CoachingContext,
    ) -> GeneratedCoachingReply:
        assert question
        assert context.context_version == COACHING_CONTEXT_VERSION
        self.conversation = conversation
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.mark.parametrize(
    ("question", "expected_reference", "expected_text"),
    (
        (
            "What should be my pace for tomorrow recovery run?",
            "plan:next-session:1",
            "5:20/km to 5:50/km",
        ),
        ("How fast can I run a 5K?", "fitness:5k", "18:03"),
        ("Is my marathon goal achievable?", "fitness:marathon", "3:11:01"),
        ("What does my current form mean?", "workload:2026-09-06", "form index"),
        ("How did today's run go?", "plan:latest-session", "easier than planned"),
        ("Summarize my training", "training:history", "311.9 km across 22 runs"),
    ),
)
def test_deterministic_coach_answers_common_questions_from_evidence(
    question: str,
    expected_reference: str,
    expected_text: str,
) -> None:
    service = ConversationalCoachService(
        context_loader=FakeLoader(),
        language_model=None,
        provider_limitation="OpenAI disabled for this test.",
    )

    reply = service.answer(athlete_id=ATHLETE_ID, question=question)

    assert reply.mode == "deterministic"
    assert expected_reference in reply.evidence_ids
    assert expected_text in reply.answer
    assert any("OpenAI disabled" in limitation for limitation in reply.limitations)
    if "recovery" in question.casefold():
        assert reply.evidence_ids == ("plan:next-session:1",)
        assert "slower end" in reply.answer
        assert reply.answer.startswith("Run 8.5 km on 2026-09-07 at 5:20/km to 5:50/km.")
        assert "45:20-49:35" in reply.answer
    if "How fast" in question:
        assert reply.answer.startswith("Your current 5k estimate is 18:03 (3:37/km)")
    if "achievable" in question:
        assert reply.answer.startswith("Not yet—your 3:10:00 marathon target")
        assert "1:01 faster" in reply.answer


def test_medical_question_never_reaches_language_model() -> None:
    model = FakeModel(
        GeneratedCoachingReply(
            answer="Unsafe",
            evidence_ids=("training:history",),
            limitations=(),
        )
    )
    service = ConversationalCoachService(context_loader=FakeLoader(), language_model=model)

    reply = service.answer(
        athlete_id=ATHLETE_ID,
        question="Can you diagnose this knee pain?",
    )

    assert reply.mode == "deterministic"
    assert "cannot diagnose" in reply.answer
    assert model.conversation == ()


def test_tomorrow_is_not_confused_with_a_later_planned_session() -> None:
    service = ConversationalCoachService(context_loader=LatePlanLoader(), language_model=None)

    reply = service.answer(athlete_id=ATHLETE_ID, question="Suggest tomorrow's session")

    assert reply.mode == "deterministic"
    assert reply.answer.startswith("No run is scheduled tomorrow, 2026-09-09.")
    assert "Your next planned session is 2026-09-14" in reply.answer


def test_temporally_ungrounded_model_reply_falls_back() -> None:
    model = FakeModel(
        GeneratedCoachingReply(
            answer="Tomorrow is the 2026-09-14 easy aerobic run.",
            evidence_ids=("plan:next-session:1",),
            limitations=(),
        )
    )
    service = ConversationalCoachService(context_loader=LatePlanLoader(), language_model=model)

    reply = service.answer(athlete_id=ATHLETE_ID, question="Suggest tomorrow's session")

    assert reply.mode == "deterministic"
    assert reply.answer.startswith("No run is scheduled tomorrow, 2026-09-09.")
    assert any("incorrect relative date" in limitation for limitation in reply.limitations)


def test_valid_structured_model_reply_is_returned_with_provenance() -> None:
    model = FakeModel(
        GeneratedCoachingReply(
            answer="Your next run is the scheduled easy 8.5 km session.",
            evidence_ids=("plan:next-session:1",),
            limitations=("Adjust for symptoms not represented in the data.",),
        )
    )
    service = ConversationalCoachService(context_loader=FakeLoader(), language_model=model)
    conversation = tuple(
        ConversationTurn(role="user" if index % 2 == 0 else "assistant", content=f"Turn {index}")
        for index in range(10)
    )

    reply = service.answer(
        athlete_id=ATHLETE_ID,
        question="What is next?",
        conversation=conversation,
    )

    assert reply.mode == "openai"
    assert reply.model == "test-model"
    assert reply.context_version == COACHING_CONTEXT_VERSION
    assert reply.evidence_ids == ("plan:next-session:1",)
    assert model.conversation == conversation[-8:]


@pytest.mark.parametrize(
    "bad_reply",
    (
        GeneratedCoachingReply(
            answer="Invented fact.",
            evidence_ids=("database:secret",),
            limitations=(),
        ),
        GeneratedCoachingReply(
            answer="You will definitely run this time; it is guaranteed.",
            evidence_ids=("fitness:5k",),
            limitations=(),
        ),
    ),
)
def test_failed_review_falls_back_to_deterministic_answer(
    bad_reply: GeneratedCoachingReply,
) -> None:
    service = ConversationalCoachService(
        context_loader=FakeLoader(),
        language_model=FakeModel(bad_reply),
    )

    reply = service.answer(athlete_id=ATHLETE_ID, question="How fast can I run a 5K?")

    assert reply.mode == "deterministic"
    assert reply.evidence_ids == ("fitness:5k",)
    assert any(
        "deterministic" in limitation or "unsupported" in limitation
        for limitation in reply.limitations
    )


def test_provider_failure_falls_back_without_exposing_provider_body() -> None:
    service = ConversationalCoachService(
        context_loader=FakeLoader(),
        language_model=FakeModel(LanguageModelError("Provider unavailable.")),
    )

    reply = service.answer(athlete_id=ATHLETE_ID, question="Summarize my training")

    assert reply.mode == "deterministic"
    assert "Provider unavailable." in reply.limitations


def test_future_plan_question_separates_current_pace_from_future_adaptation() -> None:
    service = ConversationalCoachService(context_loader=FakeLoader(), language_model=None)

    reply = service.answer(
        athlete_id=ATHLETE_ID,
        question=("If I stuck to the plan, what would be my pace for my marathon on 31.01.2027?"),
    )

    assert "4:32/km" in reply.answer
    assert "current-readiness" in reply.answer
    assert reply.evidence_ids == ("fitness:marathon",)
    assert "Future adaptation" in reply.limitations[-1]


class FakeTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.payload: dict[str, object] = {}

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        self.payload = payload
        return self.response


def test_openai_adapter_requests_stateless_structured_output() -> None:
    generated = {
        "answer": "The next session is easy.",
        "evidence_ids": ["plan:next-session:1"],
        "limitations": [],
    }
    transport = FakeTransport({"output_text": json.dumps(generated)})
    model = OpenAIResponsesLanguageModel(model="gpt-test", transport=transport)

    reply = model.generate(
        question="What is next?",
        conversation=(),
        context=_context(),
    )

    assert reply.answer == "The next session is easy."
    assert transport.payload["model"] == "gpt-test"
    assert transport.payload["store"] is False
    instructions = str(transport.payload["instructions"])
    assert "directly answers the athlete's exact question" in instructions
    assert "practical advice" in instructions
    assert "natural plain English" in instructions
    assert "never mention evidence IDs" in instructions
    assert "Do not begin by reciting the active plan" in instructions
    assert "'tomorrow' is exactly one calendar day later" in instructions
    text = transport.payload["text"]
    assert isinstance(text, dict)
    assert text["format"]["type"] == "json_schema"
    serialized_input = str(transport.payload["input"])
    assert str(ATHLETE_ID) not in serialized_input
    assert "latitude" not in serialized_input


def test_openai_adapter_reads_nested_output_and_rejects_invalid_json() -> None:
    valid = FakeTransport(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "answer": "Use the plan.",
                                    "evidence_ids": ["plan:tracking"],
                                    "limitations": [],
                                }
                            ),
                        }
                    ],
                }
            ]
        }
    )
    assert (
        OpenAIResponsesLanguageModel(model="gpt-test", transport=valid)
        .generate(question="Plan?", conversation=(), context=_context())
        .answer
        == "Use the plan."
    )

    invalid = OpenAIResponsesLanguageModel(
        model="gpt-test",
        transport=FakeTransport({"output_text": "not-json"}),
    )
    with pytest.raises(LanguageModelError, match="invalid structured"):
        invalid.generate(question="Plan?", conversation=(), context=_context())


class FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self.body


def test_url_transport_uses_authorization_without_putting_key_in_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str | None, float, bytes | None]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeHttpResponse:
        assert isinstance(request, Request)
        captured.append(
            (
                request.full_url,
                request.get_header("Authorization"),
                timeout,
                cast(bytes | None, request.data),
            )
        )
        return FakeHttpResponse(b'{"output_text":"ok"}')

    monkeypatch.setattr(chat, "urlopen", fake_urlopen)

    result = UrlLibResponsesTransport(api_key="private-key", timeout_seconds=12).create(
        {"model": "gpt-test", "store": False}
    )

    assert result["output_text"] == "ok"
    assert captured[0][:3] == (
        "https://api.openai.com/v1/responses",
        "Bearer private-key",
        12,
    )
    assert b"private-key" not in (captured[0][3] or b"")


def test_database_loader_builds_minimized_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workload = SimpleNamespace(
        local_date=date(2026, 9, 6),
        daily_load=60.0,
        acute_load=70.0,
        chronic_load=74.2,
        form_index=4.2,
        coverage_pct=100.0,
        load_method="duration_minutes_v1",
        algorithm_version="daily_load_v1",
    )
    overview = SimpleNamespace(
        as_of_date=date(2026, 9, 6),
        data_start_date=date(2024, 5, 21),
        data_end_date=date(2026, 9, 6),
        total_runs=143,
        total_distance_km=1_500.0,
        last_7_days=SimpleNamespace(runs=6, distance_km=77.0),
        last_28_days=SimpleNamespace(runs=22, distance_km=311.9),
        workload=workload,
    )
    personal_best = SimpleNamespace(
        distance=StandardDistance.FIVE_K,
        elapsed_time_seconds=1_128.0,
        pace_seconds_per_km=225.6,
        achieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        verification_status=PerformanceLabel.VERIFIED_MAX_EFFORT,
    )
    estimate = SimpleNamespace(
        distance=StandardDistance.FIVE_K,
        fitness_potential_time_seconds=1_083.0,
        race_readiness_time_seconds=1_083.0,
        optimistic_time_seconds=1_072.0,
        conservative_time_seconds=1_094.0,
        race_readiness_pace_seconds_per_km=216.6,
        preparation_score=1.0,
        confidence="high",
    )
    current_fitness = SimpleNamespace(
        as_of_date=date(2026, 9, 6),
        algorithm_version="training_context_fitness_v2",
        training=SimpleNamespace(
            distance_84d_km=748.5,
            longest_run_84d_km=28.0,
            distance_365d_km=1_468.8,
            quality_sessions_84d=10,
        ),
        estimates=(estimate,),
    )
    performance = SimpleNamespace(
        personal_bests=(personal_best,),
        current_fitness=current_fitness,
        limitations=("Experimental model.",),
    )
    persisted = SimpleNamespace(
        version=2,
        preview={
            "goal": {
                "distance": "marathon",
                "race_date": "2027-01-31",
                "target_time_seconds": 11_400.0,
                "days_per_week": 6,
            },
            "recommended_target_seconds": 11_461.0,
            "first_week": [
                {
                    "scheduled_date": "2026-09-06",
                    "kind": "easy",
                    "title": "Recovery run",
                    "distance_km": 10.0,
                    "pace": {
                        "faster_seconds_per_km": 330.0,
                        "slower_seconds_per_km": 390.0,
                    },
                    "purpose": "Absorb prior training.",
                },
                {
                    "scheduled_date": "2026-09-07",
                    "kind": "easy",
                    "title": "Easy aerobic run",
                    "distance_km": 8.5,
                    "pace": {
                        "faster_seconds_per_km": 320.0,
                        "slower_seconds_per_km": 350.0,
                    },
                    "purpose": "Maintain aerobic frequency.",
                },
            ],
        },
    )
    completed_session = SimpleNamespace(
        scheduled_date=date(2026, 9, 6),
        title="Recovery run",
        target_distance_km=10.0,
        status="completed",
        kind="easy",
        matched_activity_date=date(2026, 9, 6),
        matched_activity_name="Morning recovery",
        actual_distance_km=12.0,
        actual_pace_seconds_per_km=384.0,
        classified_as="recovery",
        distance_completion_pct=120.0,
        pace_status="easier_than_planned",
    )
    upcoming_session = SimpleNamespace(
        scheduled_date=date(2026, 9, 7),
        title="Easy aerobic run",
        target_distance_km=8.5,
        status="upcoming",
        kind="easy",
        pace_status="not_applicable",
    )
    tracking = SimpleNamespace(
        race_date=date(2027, 1, 31),
        recommendation="Continue with the next scheduled session.",
        status="in_progress",
        as_of_date=date(2026, 9, 6),
        current_week_number=1,
        completed_weeks=0,
        total_weeks=21,
        planned_distance_to_date_km=10.0,
        actual_distance_to_date_km=11.0,
        adherence_pct=110.0,
        recommendation_code="continue_as_planned",
        sessions=(completed_session, upcoming_session),
    )

    class AnalyticsService:
        def __init__(self, database: object) -> None:
            assert database is not None

        def overview(self, **kwargs: object) -> object:
            del kwargs
            return overview

    class PerformanceService:
        def __init__(self, database: object) -> None:
            assert database is not None

        def overview(self, **kwargs: object) -> object:
            del kwargs
            return performance

    class PlanService:
        def __init__(self, database: object) -> None:
            assert database is not None

        def load_active(self, **kwargs: object) -> object:
            del kwargs
            return persisted

    class TrackingService:
        def __init__(self, database: object) -> None:
            assert database is not None

        def overview(self, **kwargs: object) -> object:
            del kwargs
            return tracking

    monkeypatch.setattr(chat, "AnalyticsQueryService", AnalyticsService)
    monkeypatch.setattr(chat, "PerformanceQueryService", PerformanceService)
    monkeypatch.setattr(chat, "TrainingPlanPersistenceService", PlanService)
    monkeypatch.setattr(chat, "TrainingPlanTrackingService", TrackingService)

    context = DatabaseCoachingContextLoader(cast(Session, SimpleNamespace())).load(ATHLETE_ID)

    assert "fitness:5k" in context.evidence_ids
    assert "goal:active" in context.evidence_ids
    assert "plan:latest-session" in context.evidence_ids
    assert "plan:next-session:1" in context.evidence_ids
    next_session = context.item("plan:next-session:1")
    assert next_session is not None
    assert next_session.facts["pace_range"] == "5:20/km to 5:50/km"
    latest_session = context.item("plan:latest-session")
    assert latest_session is not None
    assert latest_session.facts["actual_pace"] == "6:24/km"
    assert latest_session.facts["pace_status"] == "easier_than_planned"
    serialized = context.model_dump_json()
    assert str(ATHLETE_ID) not in serialized
    assert "latitude" not in serialized
    assert "source_file" not in serialized


def test_database_loader_tolerates_missing_active_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingPlanService:
        def __init__(self, database: object) -> None:
            del database

        def load_active(self, **kwargs: object) -> object:
            del kwargs
            raise TrainingPlanQueryError("missing")

    monkeypatch.setattr(chat, "TrainingPlanPersistenceService", MissingPlanService)
    loader = DatabaseCoachingContextLoader(cast(Session, SimpleNamespace()))
    evidence: list[EvidenceItem] = []
    limitations: list[str] = []

    loader._append_plan_evidence(ATHLETE_ID, evidence, limitations)

    assert evidence == []
    assert limitations == ["No active training plan is available for goal-specific advice."]


def test_builder_uses_deterministic_fallback_until_openai_is_fully_configured() -> None:
    disabled = build_conversational_coach(
        cast(Session, SimpleNamespace()),
        Settings(environment="test", llm_provider="disabled"),
    )
    incomplete = build_conversational_coach(
        cast(Session, SimpleNamespace()),
        Settings(environment="test", llm_provider="openai", openai_model="gpt-test"),
    )

    assert isinstance(disabled, ConversationalCoachService)
    assert isinstance(incomplete, ConversationalCoachService)


def test_reply_contract_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        CoachingReply(
            answer="No evidence.",
            evidence_ids=(),
            limitations=(),
            mode="deterministic",
            model=None,
            context_version="v1",
            prompt_version="v1",
        )
