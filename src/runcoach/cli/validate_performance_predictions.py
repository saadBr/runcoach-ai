"""Run leakage-safe chronological validation of race-time baselines."""

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
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
from runcoach.config import get_settings

DEFAULT_INPUT = Path("data/private/ml/performance-label-audit.csv")
DEFAULT_OUTPUT = Path("data/private/ml/performance-validation.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate deterministic race-time baselines from a frozen label-audit export "
            "using strictly earlier verified outcomes."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Label-audit CSV under RUNCOACH_PRIVATE_DATA_DIR.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON artifact path under RUNCOACH_PRIVATE_DATA_DIR.",
    )
    return parser


def _private_path(path: Path, private_data_dir: Path) -> Path:
    resolved_path = path.resolve()
    resolved_private_root = private_data_dir.resolve()
    if not resolved_path.is_relative_to(resolved_private_root):
        raise ValueError("Validation inputs and artifacts must remain under private data.")
    return resolved_path


def _required(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise ValueError(f"Verified label-audit row is missing {field}.")
    return value.strip()


def _read_observations(path: Path) -> tuple[str, tuple[PerformanceObservation, ...]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as input_file:
            rows = tuple(csv.DictReader(input_file))
    except OSError as error:
        raise ValueError(f"Could not read label-audit CSV: {error}") from error

    verified_rows = tuple(row for row in rows if row.get("review_status") == "verified")
    versions = {_required(row, "dataset_version") for row in verified_rows}
    if len(versions) > 1:
        raise ValueError("Verified rows contain more than one dataset version.")

    observations: list[PerformanceObservation] = []
    for row in verified_rows:
        try:
            activity_id = UUID(_required(row, "activity_id"))
            performance = VerifiedPerformance(
                activity_id=activity_id,
                distance=StandardDistance(_required(row, "matched_distance")),
                elapsed_time_seconds=float(_required(row, "verified_elapsed_time_seconds")),
                achieved_at=datetime.fromisoformat(_required(row, "achieved_at")),
                label=PerformanceLabel(_required(row, "review_label")),
            )
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid verified label-audit row: {error}") from error
        observations.append(
            PerformanceObservation(
                observation_id=activity_id,
                performance=performance,
            )
        )
    return (next(iter(versions), "unknown"), tuple(observations))


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported validation artifact value: {type(value).__name__}")


def _write_report(
    path: Path,
    report: PerformanceValidationReport,
    *,
    dataset_version: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "dataset_version": dataset_version,
        "report": asdict(report),
    }
    path.write_text(
        json.dumps(artifact, default=_json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _public_summary(
    report: PerformanceValidationReport,
    *,
    dataset_version: str,
    output: Path,
) -> dict[str, object]:
    aggregate_metrics = tuple(
        {
            "baseline": item.baseline,
            "predictions": item.predictions,
            "mean_absolute_error_seconds": item.mean_absolute_error_seconds,
            "median_absolute_error_seconds": item.median_absolute_error_seconds,
            "mean_absolute_percentage_error": item.mean_absolute_percentage_error,
            "mean_signed_error_seconds": item.mean_signed_error_seconds,
        }
        for item in report.metrics
        if item.target_distance is None
    )
    return {
        "validation_version": report.validation_version,
        "dataset_version": dataset_version,
        "output": str(output),
        "status": report.status,
        "verified_labels": report.verified_labels,
        "represented_distances": tuple(item.value for item in report.represented_distances),
        "chronological_targets": report.chronological_targets,
        "candidate_model_eligible": report.candidate_model_eligible,
        "eligibility_reasons": report.eligibility_reasons,
        "aggregate_metrics": aggregate_metrics,
        "leakage_rule": report.leakage_rule,
    }


def main(arguments: list[str] | None = None) -> int:
    """Validate a frozen private label-audit export and write detailed predictions."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    try:
        input_path = _private_path(parsed.input, settings.private_data_dir)
        output_path = _private_path(parsed.output, settings.private_data_dir)
        dataset_version, observations = _read_observations(input_path)
    except ValueError as error:
        parser.error(str(error))

    report = evaluate_performance_baselines(observations)
    _write_report(output_path, report, dataset_version=dataset_version)
    print(
        json.dumps(
            _public_summary(
                report,
                dataset_version=dataset_version,
                output=output_path,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
