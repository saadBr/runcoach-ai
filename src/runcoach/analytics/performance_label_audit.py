"""Private label-audit storage and chronological validation orchestration."""

import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import UUID

from runcoach.analytics.performance import (
    PerformanceLabel,
    StandardDistance,
    VerifiedPerformance,
)
from runcoach.analytics.performance_validation import (
    PerformanceObservation,
    PerformanceValidationReport,
    evaluate_performance_baselines,
)

LABEL_AUDIT_RELATIVE_PATH = Path("ml/performance-label-audit.csv")
VALIDATION_RELATIVE_PATH = Path("ml/performance-validation.json")
REQUIRED_COLUMNS = frozenset(
    {
        "dataset_version",
        "activity_id",
        "activity_name",
        "achieved_at",
        "matched_distance",
        "measured_distance_m",
        "recorded_elapsed_time_seconds",
        "distance_deviation_pct",
        "review_status",
        "review_label",
        "verified_elapsed_time_seconds",
        "review_notes",
    }
)
_AUDIT_WRITE_LOCK = Lock()


class LabelAuditError(RuntimeError):
    """Raised when private label-audit state cannot be read or updated safely."""


class LabelReviewStatus(StrEnum):
    """Human review state for one standard-distance candidate."""

    UNREVIEWED = "unreviewed"
    VERIFIED = "verified"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class PerformanceLabelCandidate:
    """Minimal candidate details approved for the local review UI."""

    activity_id: UUID
    activity_name: str | None
    achieved_at: datetime
    matched_distance: StandardDistance
    measured_distance_m: float
    recorded_elapsed_time_seconds: float
    distance_deviation_pct: float
    review_status: LabelReviewStatus
    review_label: PerformanceLabel | None
    verified_elapsed_time_seconds: float | None
    review_notes: str | None


@dataclass(frozen=True, slots=True)
class PerformanceLabelAudit:
    """Current private review queue and its aggregate state."""

    dataset_version: str
    total_rows: int
    verified_rows: int
    excluded_rows: int
    unreviewed_rows: int
    candidates: tuple[PerformanceLabelCandidate, ...]


@dataclass(frozen=True, slots=True)
class LabelReviewDecision:
    """Validated update for one candidate row."""

    review_status: LabelReviewStatus
    review_label: PerformanceLabel | None = None
    verified_elapsed_time_seconds: float | None = None
    review_notes: str | None = None

    def __post_init__(self) -> None:
        notes = self.review_notes.strip() if self.review_notes is not None else None
        if notes is not None and len(notes) > 500:
            raise ValueError("Review notes cannot exceed 500 characters.")
        if self.review_status is LabelReviewStatus.VERIFIED:
            if self.review_label is None:
                raise ValueError("A verified candidate requires a performance label.")
            if (
                self.verified_elapsed_time_seconds is None
                or self.verified_elapsed_time_seconds <= 0
            ):
                raise ValueError("A verified candidate requires a positive elapsed time.")
        elif self.review_label is not None or self.verified_elapsed_time_seconds is not None:
            raise ValueError("Only verified candidates may have a label and verified time.")
        object.__setattr__(self, "review_notes", notes or None)


def label_audit_path(private_data_dir: Path) -> Path:
    """Return the fixed private audit path without accepting user-controlled paths."""

    return private_data_dir.resolve() / LABEL_AUDIT_RELATIVE_PATH


def validation_artifact_path(private_data_dir: Path) -> Path:
    """Return the fixed private validation artifact path."""

    return private_data_dir.resolve() / VALIDATION_RELATIVE_PATH


def review_token(
    *,
    dataset_version: str,
    activity_id: UUID,
) -> str:
    """Return a stable opaque token without exposing the private activity UUID."""

    return sha256(f"{dataset_version}:{activity_id}".encode()).hexdigest()


def candidate_for_review_token(
    audit: PerformanceLabelAudit,
    token: str,
) -> PerformanceLabelCandidate:
    """Resolve exactly one opaque review token inside trusted application code."""

    matches = tuple(
        candidate
        for candidate in audit.candidates
        if review_token(
            dataset_version=audit.dataset_version,
            activity_id=candidate.activity_id,
        )
        == token
    )
    if len(matches) != 1:
        raise LabelAuditError("Label-audit review token was not found exactly once.")
    return matches[0]


def _required(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise LabelAuditError(f"Label-audit row is missing {field}.")
    return value.strip()


def _optional(row: dict[str, str | None], field: str) -> str | None:
    value = row.get(field)
    if value is None or not value.strip():
        return None
    return value.strip()


def _positive_float(row: dict[str, str | None], field: str) -> float:
    try:
        value = float(_required(row, field))
    except ValueError as error:
        raise LabelAuditError(f"Label-audit {field} must be numeric.") from error
    if value <= 0:
        raise LabelAuditError(f"Label-audit {field} must be positive.")
    return value


def _optional_positive_float(
    row: dict[str, str | None],
    field: str,
) -> float | None:
    raw = _optional(row, field)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise LabelAuditError(f"Label-audit {field} must be numeric.") from error
    if value <= 0:
        raise LabelAuditError(f"Label-audit {field} must be positive.")
    return value


def _candidate(row: dict[str, str | None]) -> PerformanceLabelCandidate:
    try:
        status = LabelReviewStatus(_required(row, "review_status"))
        label_value = _optional(row, "review_label")
        label = PerformanceLabel(label_value) if label_value is not None else None
        verified_seconds = _optional_positive_float(row, "verified_elapsed_time_seconds")
        decision = LabelReviewDecision(
            review_status=status,
            review_label=label,
            verified_elapsed_time_seconds=verified_seconds,
            review_notes=_optional(row, "review_notes"),
        )
        return PerformanceLabelCandidate(
            activity_id=UUID(_required(row, "activity_id")),
            activity_name=_optional(row, "activity_name"),
            achieved_at=datetime.fromisoformat(_required(row, "achieved_at")),
            matched_distance=StandardDistance(_required(row, "matched_distance")),
            measured_distance_m=_positive_float(row, "measured_distance_m"),
            recorded_elapsed_time_seconds=_positive_float(
                row,
                "recorded_elapsed_time_seconds",
            ),
            distance_deviation_pct=float(_required(row, "distance_deviation_pct")),
            review_status=decision.review_status,
            review_label=decision.review_label,
            verified_elapsed_time_seconds=decision.verified_elapsed_time_seconds,
            review_notes=decision.review_notes,
        )
    except (TypeError, ValueError) as error:
        raise LabelAuditError(f"Invalid label-audit row: {error}") from error


def _read_rows(path: Path) -> tuple[tuple[str, ...], list[dict[str, str | None]]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            fieldnames = tuple(reader.fieldnames or ())
            if not REQUIRED_COLUMNS.issubset(fieldnames):
                missing = sorted(REQUIRED_COLUMNS.difference(fieldnames))
                raise LabelAuditError(
                    f"Label-audit CSV is missing required columns: {', '.join(missing)}."
                )
            rows = list(reader)
    except OSError as error:
        raise LabelAuditError(f"Could not read label-audit CSV: {error}") from error
    return fieldnames, rows


def load_label_audit(path: Path) -> PerformanceLabelAudit:
    """Read and validate the private candidate review queue."""

    _, rows = _read_rows(path)
    candidates = tuple(_candidate(row) for row in rows)
    activity_ids = tuple(candidate.activity_id for candidate in candidates)
    if len(set(activity_ids)) != len(activity_ids):
        raise LabelAuditError("Label-audit CSV contains duplicate activity IDs.")
    versions = {_required(row, "dataset_version") for row in rows}
    if len(versions) > 1:
        raise LabelAuditError("Label-audit CSV contains multiple dataset versions.")
    return PerformanceLabelAudit(
        dataset_version=next(iter(versions), "unknown"),
        total_rows=len(candidates),
        verified_rows=sum(
            candidate.review_status is LabelReviewStatus.VERIFIED for candidate in candidates
        ),
        excluded_rows=sum(
            candidate.review_status is LabelReviewStatus.EXCLUDED for candidate in candidates
        ),
        unreviewed_rows=sum(
            candidate.review_status is LabelReviewStatus.UNREVIEWED for candidate in candidates
        ),
        candidates=candidates,
    )


def _write_rows_atomic(
    path: Path,
    *,
    fieldnames: Sequence[str],
    rows: Sequence[dict[str, str | None]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            writer = csv.DictWriter(output_file, fieldnames=fieldnames, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise LabelAuditError(f"Could not update label-audit CSV: {error}") from error


def update_label_review(
    path: Path,
    *,
    activity_id: UUID,
    decision: LabelReviewDecision,
) -> PerformanceLabelAudit:
    """Atomically update exactly one candidate and return the refreshed queue."""

    with _AUDIT_WRITE_LOCK:
        fieldnames, rows = _read_rows(path)
        matches = [row for row in rows if row.get("activity_id") == str(activity_id)]
        if len(matches) != 1:
            raise LabelAuditError("Label-audit activity was not found exactly once.")
        row = matches[0]
        row["review_status"] = decision.review_status.value
        row["review_label"] = (
            decision.review_label.value if decision.review_label is not None else ""
        )
        row["verified_elapsed_time_seconds"] = (
            str(decision.verified_elapsed_time_seconds)
            if decision.verified_elapsed_time_seconds is not None
            else ""
        )
        row["review_notes"] = decision.review_notes or ""
        _write_rows_atomic(path, fieldnames=fieldnames, rows=rows)
        return load_label_audit(path)


def observations_from_audit(
    audit: PerformanceLabelAudit,
) -> tuple[PerformanceObservation, ...]:
    """Convert verified review rows into chronological validation observations."""

    return tuple(
        PerformanceObservation(
            observation_id=candidate.activity_id,
            performance=VerifiedPerformance(
                activity_id=candidate.activity_id,
                distance=candidate.matched_distance,
                elapsed_time_seconds=candidate.verified_elapsed_time_seconds,
                achieved_at=candidate.achieved_at,
                label=candidate.review_label,
            ),
        )
        for candidate in audit.candidates
        if candidate.review_status is LabelReviewStatus.VERIFIED
        and candidate.review_label is not None
        and candidate.verified_elapsed_time_seconds is not None
    )


def evaluate_label_audit(audit: PerformanceLabelAudit) -> PerformanceValidationReport:
    """Run leakage-safe chronological baselines from the current verified labels."""

    return evaluate_performance_baselines(observations_from_audit(audit))


def write_validation_artifact(
    path: Path,
    *,
    audit: PerformanceLabelAudit,
    report: PerformanceValidationReport,
) -> None:
    """Atomically persist the detailed private validation report."""

    artifact = {
        "dataset_version": audit.dataset_version,
        "report": asdict(report),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            json.dump(
                artifact,
                output_file,
                default=lambda value: (
                    value.isoformat() if isinstance(value, datetime) else str(value)
                ),
                indent=2,
                sort_keys=True,
            )
            output_file.write("\n")
        temporary_path.replace(path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise LabelAuditError(f"Could not write validation artifact: {error}") from error


def update_and_validate(
    *,
    private_data_dir: Path,
    activity_id: UUID,
    decision: LabelReviewDecision,
) -> tuple[PerformanceLabelAudit, PerformanceValidationReport]:
    """Apply one human decision and refresh the private validation artifact."""

    audit = update_label_review(
        label_audit_path(private_data_dir),
        activity_id=activity_id,
        decision=decision,
    )
    report = evaluate_label_audit(audit)
    write_validation_artifact(
        validation_artifact_path(private_data_dir),
        audit=audit,
        report=report,
    )
    return audit, report
