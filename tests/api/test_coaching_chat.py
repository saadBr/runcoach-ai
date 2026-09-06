"""Tests for the evidence-grounded conversational coaching endpoint."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from runcoach.api.routes import coaching as coaching_routes
from runcoach.coaching.chat import CoachingChatError, CoachingReply
from runcoach.config import Settings, get_settings
from runcoach.db.session import get_db_session
from runcoach.main import app

ATHLETE_ID = UUID("018f0000-0000-7000-8000-000000000001")


@pytest.fixture
def configured_client(client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test",
        athlete_id=ATHLETE_ID,
    )
    app.dependency_overrides[get_db_session] = lambda: object()
    yield client
    app.dependency_overrides.clear()


def _reply() -> CoachingReply:
    return CoachingReply(
        answer="Next is an easy 8.5 km run.",
        evidence_ids=("plan:next-session:1",),
        limitations=("Adjust for symptoms not represented in the data.",),
        mode="deterministic",
        model=None,
        context_version="coaching_context_v1",
        prompt_version="evidence_coach_v1",
    )


def test_chat_endpoint_passes_bounded_typed_conversation(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[UUID, str, int]] = []

    class FakeCoach:
        def answer(self, **kwargs: object) -> CoachingReply:
            athlete_id = kwargs["athlete_id"]
            question = kwargs["question"]
            conversation = kwargs["conversation"]
            assert isinstance(athlete_id, UUID)
            assert isinstance(question, str)
            assert isinstance(conversation, tuple)
            captured.append((athlete_id, question, len(conversation)))
            return _reply()

    monkeypatch.setattr(
        coaching_routes,
        "build_conversational_coach",
        lambda session, settings: FakeCoach(),
    )

    response = configured_client.post(
        "/api/v1/coaching/chat",
        json={
            "message": "What should I run tomorrow?",
            "conversation": [
                {"role": "user", "content": "How is my plan?"},
                {"role": "assistant", "content": "It is on track."},
            ],
        },
    )

    assert response.status_code == 200
    assert captured == [(ATHLETE_ID, "What should I run tomorrow?", 2)]
    assert response.json()["evidence_ids"] == ["plan:next-session:1"]
    assert response.json()["mode"] == "deterministic"


@pytest.mark.parametrize(
    "body",
    (
        {"message": ""},
        {"message": "Question", "unexpected": True},
        {
            "message": "Question",
            "conversation": [{"role": "user", "content": "x"}] * 9,
        },
    ),
)
def test_chat_endpoint_rejects_invalid_contract(
    configured_client: TestClient,
    body: dict[str, object],
) -> None:
    response = configured_client.post("/api/v1/coaching/chat", json=body)

    assert response.status_code == 422


def test_chat_endpoint_translates_unavailable_evidence(
    configured_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCoach:
        def answer(self, **kwargs: object) -> CoachingReply:
            del kwargs
            raise CoachingChatError("No calculated training evidence is available.")

    monkeypatch.setattr(
        coaching_routes,
        "build_conversational_coach",
        lambda session, settings: FailingCoach(),
    )

    response = configured_client.post(
        "/api/v1/coaching/chat",
        json={"message": "How is my fitness?"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "No calculated training evidence is available."}
