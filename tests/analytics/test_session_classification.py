"""Tests for deterministic activity-title session classification."""

import pytest

from runcoach.analytics.session_classification import (
    SESSION_CLASSIFICATION_VERSION,
    ClassificationConfidence,
    SessionClassification,
    SessionKind,
    classify_session,
)


@pytest.mark.parametrize(
    ("title", "primary_kind", "tags", "confidence"),
    (
        (
            "Easy Aerobic Run",
            SessionKind.EASY,
            (SessionKind.EASY,),
            ClassificationConfidence.HIGH,
        ),
        (
            "Progressive long run",
            SessionKind.PROGRESSIVE,
            (SessionKind.PROGRESSIVE, SessionKind.LONG),
            ClassificationConfidence.HIGH,
        ),
        (
            "Hill Session 3K WU 12 200m Hills",
            SessionKind.HILLS,
            (SessionKind.HILLS,),
            ClassificationConfidence.HIGH,
        ),
        (
            "3K WU 25 tempo 1 5K CD",
            SessionKind.TEMPO,
            (SessionKind.TEMPO,),
            ClassificationConfidence.HIGH,
        ),
        (
            "Bab en bab race",
            SessionKind.RACE,
            (SessionKind.RACE,),
            ClassificationConfidence.HIGH,
        ),
        (
            "6 \N{MULTIPLICATION SIGN} 1K",
            SessionKind.INTERVALS,
            (SessionKind.INTERVALS,),
            ClassificationConfidence.MEDIUM,
        ),
        (
            "Morning Run",
            SessionKind.UNCLASSIFIED,
            (SessionKind.UNCLASSIFIED,),
            ClassificationConfidence.LOW,
        ),
        (
            None,
            SessionKind.UNCLASSIFIED,
            (SessionKind.UNCLASSIFIED,),
            ClassificationConfidence.LOW,
        ),
    ),
)
def test_classify_session(
    title: str | None,
    primary_kind: SessionKind,
    tags: tuple[SessionKind, ...],
    confidence: ClassificationConfidence,
) -> None:
    result = classify_session(title)

    assert result.algorithm_version == SESSION_CLASSIFICATION_VERSION
    assert result.primary_kind is primary_kind
    assert result.tags == tags
    assert result.confidence is confidence


def test_classification_preserves_multiple_meaningful_tags() -> None:
    result = classify_session("Progressive Long Run")

    assert result.primary_kind is SessionKind.PROGRESSIVE
    assert result.tags == (SessionKind.PROGRESSIVE, SessionKind.LONG)
    assert result.matched_terms == ("progressive", "long run")
    assert result.has_tag(SessionKind.PROGRESSIVE)
    assert result.has_tag(SessionKind.LONG)
    assert not result.has_tag(SessionKind.RACE)
    assert result.is_quality_session


def test_classification_normalizes_accents_and_separators() -> None:
    result = classify_session("  Séance_de-CÔTES  ")

    assert result.normalized_title == "seance de cotes"
    assert result.primary_kind is SessionKind.HILLS
    assert result.matched_terms == ("cotes",)


def test_explicit_interval_keyword_has_high_confidence() -> None:
    result = classify_session("8 x 400m intervals")

    assert result.primary_kind is SessionKind.INTERVALS
    assert result.confidence is ClassificationConfidence.HIGH
    assert result.matched_terms == ("intervals",)


def test_empty_title_is_unclassified() -> None:
    result = classify_session("   ")

    assert result.normalized_title == ""
    assert result.primary_kind is SessionKind.UNCLASSIFIED
    assert result.tags == (SessionKind.UNCLASSIFIED,)
    assert result.matched_terms == ()
    assert not result.is_quality_session


def test_classification_requires_primary_kind_to_be_a_tag() -> None:
    with pytest.raises(ValueError, match="primary session kind"):
        SessionClassification(
            algorithm_version=SESSION_CLASSIFICATION_VERSION,
            normalized_title="easy run",
            primary_kind=SessionKind.EASY,
            tags=(SessionKind.LONG,),
            matched_terms=("easy",),
            confidence=ClassificationConfidence.HIGH,
        )


def test_classification_requires_at_least_one_tag() -> None:
    with pytest.raises(ValueError, match="at least one tag"):
        SessionClassification(
            algorithm_version=SESSION_CLASSIFICATION_VERSION,
            normalized_title="",
            primary_kind=SessionKind.UNCLASSIFIED,
            tags=(),
            matched_terms=(),
            confidence=ClassificationConfidence.LOW,
        )
