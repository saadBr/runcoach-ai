"""Deterministic session classification from athlete-authored activity titles."""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SESSION_CLASSIFICATION_VERSION: Final = "title_rules_v1"


class SessionKind(StrEnum):
    """Training-session categories derived from activity titles."""

    RACE = "race"
    HILLS = "hills"
    INTERVALS = "intervals"
    TEMPO = "tempo"
    PROGRESSIVE = "progressive"
    LONG = "long"
    EASY = "easy"
    UNCLASSIFIED = "unclassified"


class ClassificationConfidence(StrEnum):
    """Strength of the title evidence supporting a classification."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


QUALITY_SESSION_KINDS: Final[frozenset[SessionKind]] = frozenset(
    {
        SessionKind.RACE,
        SessionKind.HILLS,
        SessionKind.INTERVALS,
        SessionKind.TEMPO,
        SessionKind.PROGRESSIVE,
    }
)


@dataclass(frozen=True, slots=True)
class SessionClassification:
    """Explainable classification of one activity title."""

    algorithm_version: str
    normalized_title: str
    primary_kind: SessionKind
    tags: tuple[SessionKind, ...]
    matched_terms: tuple[str, ...]
    confidence: ClassificationConfidence

    def __post_init__(self) -> None:
        if not self.tags:
            raise ValueError("A session classification must contain at least one tag.")
        if self.primary_kind not in self.tags:
            raise ValueError("The primary session kind must also appear in the tags.")

    def has_tag(self, tag: SessionKind) -> bool:
        """Return whether the classification contains a particular tag."""

        return tag in self.tags

    @property
    def is_quality_session(self) -> bool:
        """Return whether the title identifies purposeful high-quality work."""

        return any(tag in QUALITY_SESSION_KINDS for tag in self.tags)


type PatternRule = tuple[SessionKind, tuple[re.Pattern[str], ...]]


_RULES: Final[tuple[PatternRule, ...]] = (
    (
        SessionKind.RACE,
        (
            re.compile(r"\brace\b"),
            re.compile(r"\bracing\b"),
            re.compile(r"\btime\s+trial\b"),
            re.compile(r"\bcompetition\b"),
            re.compile(r"\bchampionship\b"),
        ),
    ),
    (
        SessionKind.HILLS,
        (
            re.compile(r"\bhills?\b"),
            re.compile(r"\bhilly\b"),
            re.compile(r"\bclimbs?\b"),
            re.compile(r"\bcotes?\b"),
        ),
    ),
    (
        SessionKind.INTERVALS,
        (
            re.compile(r"\bintervals?\b"),
            re.compile(r"\brepeats?\b"),
            re.compile(r"\breps?\b"),
            re.compile(r"\bfartlek\b"),
        ),
    ),
    (
        SessionKind.TEMPO,
        (
            re.compile(r"\btempo\b"),
            re.compile(r"\bthreshold\b"),
            re.compile(r"\blactate\s+threshold\b"),
            re.compile(r"\bsteady\s+state\b"),
            re.compile(r"\bseuil\b"),
        ),
    ),
    (
        SessionKind.PROGRESSIVE,
        (
            re.compile(r"\bprogressive\b"),
            re.compile(r"\bprogression\b"),
            re.compile(r"\bnegative\s+split\b"),
        ),
    ),
    (
        SessionKind.LONG,
        (
            re.compile(r"\blong(?:\s+run)?\b"),
            re.compile(r"\bsortie\s+longue\b"),
        ),
    ),
    (
        SessionKind.EASY,
        (
            re.compile(r"\beasy\b"),
            re.compile(r"\baerobic\b"),
            re.compile(r"\brecovery\b"),
            re.compile(r"\bshakeout\b"),
            re.compile(r"\bfooting\b"),
            re.compile(r"\bz(?:one\s*)?2\b"),
        ),
    ),
)

_INTERVAL_NOTATION: Final = re.compile(
    r"\b\d+\s*x\s*\d+(?:\.\d+)?\s*(?:km|k|m|min|minute|minutes|s|sec|seconds)?\b"
)


def _normalize_title(title: str | None) -> str:
    if title is None:
        return ""

    normalized = title.replace("\N{MULTIPLICATION SIGN}", "x")
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = normalized.encode("ascii", errors="ignore").decode("ascii")
    normalized = normalized.casefold()
    normalized = re.sub(r"[_/\\-]+", " ", normalized)
    normalized = re.sub(r"[^a-z0-9+]+", " ", normalized)
    return " ".join(normalized.split())


def classify_session(title: str | None) -> SessionClassification:
    """Classify an activity title without inferring intent from pace or distance."""

    normalized_title = _normalize_title(title)
    if not normalized_title:
        return SessionClassification(
            algorithm_version=SESSION_CLASSIFICATION_VERSION,
            normalized_title="",
            primary_kind=SessionKind.UNCLASSIFIED,
            tags=(SessionKind.UNCLASSIFIED,),
            matched_terms=(),
            confidence=ClassificationConfidence.LOW,
        )

    tags: list[SessionKind] = []
    matched_terms: list[str] = []

    for kind, patterns in _RULES:
        rule_matches = [
            match.group(0) for pattern in patterns for match in pattern.finditer(normalized_title)
        ]
        if not rule_matches:
            continue

        tags.append(kind)
        matched_terms.extend(rule_matches)

    confidence = ClassificationConfidence.HIGH
    if not tags:
        interval_match = _INTERVAL_NOTATION.search(normalized_title)
        if interval_match is not None:
            tags.append(SessionKind.INTERVALS)
            matched_terms.append(interval_match.group(0))
            confidence = ClassificationConfidence.MEDIUM

    if not tags:
        tags.append(SessionKind.UNCLASSIFIED)
        confidence = ClassificationConfidence.LOW

    return SessionClassification(
        algorithm_version=SESSION_CLASSIFICATION_VERSION,
        normalized_title=normalized_title,
        primary_kind=tags[0],
        tags=tuple(tags),
        matched_terms=tuple(dict.fromkeys(matched_terms)),
        confidence=confidence,
    )
