"""Export a private, leakage-safe performance label-review dataset."""

import argparse
import csv
import json
from pathlib import Path
from uuid import UUID

from runcoach.analytics.performance import DEFAULT_DISTANCE_TOLERANCE_PCT
from runcoach.config import get_settings
from runcoach.db.performance_audit import (
    TRAINING_WINDOWS_DAYS,
    PerformanceAuditQueryService,
    PerformanceTrainingDataset,
    PerformanceTrainingRow,
)
from runcoach.db.session import SessionFactory

DEFAULT_OUTPUT = Path("data/private/ml/performance-label-audit.csv")
BASE_COLUMNS = (
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
    "prior_history_runs",
    "prior_history_days",
    "prior_acute_load",
    "prior_chronic_load",
    "prior_form_index",
    "prior_5k_best_seconds",
    "prior_10k_best_seconds",
    "prior_half_marathon_best_seconds",
    "prior_marathon_best_seconds",
)
WINDOW_COLUMNS = (
    "runs",
    "distance_km",
    "moving_hours",
    "longest_run_km",
    "weighted_pace_seconds_per_km",
    "elevation_gain_m",
    "activities_with_heart_rate",
    "duration_load_minutes",
)


def _positive_tolerance(value: str) -> float:
    try:
        tolerance = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Tolerance must be numeric.") from error

    if not 0 < tolerance <= 10:
        raise argparse.ArgumentTypeError(
            "Tolerance must be greater than zero and at most 10 percent."
        )
    return tolerance


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export standard-distance candidates with training features calculated only "
            "from evidence preceding each candidate."
        )
    )
    parser.add_argument(
        "--athlete-id",
        type=UUID,
        help="Stable athlete UUID; defaults to RUNCOACH_ATHLETE_ID.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="CSV path under RUNCOACH_PRIVATE_DATA_DIR.",
    )
    parser.add_argument(
        "--distance-tolerance-pct",
        type=_positive_tolerance,
        default=DEFAULT_DISTANCE_TOLERANCE_PCT,
        help="Maximum candidate distance deviation percentage; defaults to 3.0.",
    )
    return parser


def _private_output_path(output: Path, private_data_dir: Path) -> Path:
    resolved_output = output.resolve()
    resolved_private_root = private_data_dir.resolve()
    if not resolved_output.is_relative_to(resolved_private_root):
        raise ValueError("The label-audit CSV must remain under the private data directory.")
    return resolved_output


def _fieldnames() -> tuple[str, ...]:
    window_columns = tuple(
        f"prior_{days}d_{column}" for days in TRAINING_WINDOWS_DAYS for column in WINDOW_COLUMNS
    )
    return BASE_COLUMNS + window_columns


def _optional_csv_value(value: object | None) -> object:
    return "" if value is None else value


def _csv_row(
    row: PerformanceTrainingRow,
    *,
    dataset_version: str,
) -> dict[str, object]:
    values: dict[str, object] = {
        "dataset_version": dataset_version,
        "activity_id": str(row.activity_id),
        "activity_name": row.activity_name or "",
        "achieved_at": row.achieved_at.isoformat(),
        "matched_distance": row.matched_distance.value,
        "measured_distance_m": row.measured_distance_m,
        "recorded_elapsed_time_seconds": row.recorded_elapsed_time_seconds,
        "distance_deviation_pct": row.distance_deviation_pct,
        "review_status": row.review_status,
        "review_label": row.review_label or "",
        "verified_elapsed_time_seconds": _optional_csv_value(row.verified_elapsed_time_seconds),
        "review_notes": row.review_notes or "",
        "prior_history_runs": row.prior_history_runs,
        "prior_history_days": row.prior_history_days,
        "prior_acute_load": row.prior_acute_load if row.prior_acute_load is not None else "",
        "prior_chronic_load": (
            row.prior_chronic_load if row.prior_chronic_load is not None else ""
        ),
        "prior_form_index": row.prior_form_index if row.prior_form_index is not None else "",
        "prior_5k_best_seconds": _optional_csv_value(row.prior_5k_best_seconds),
        "prior_10k_best_seconds": _optional_csv_value(row.prior_10k_best_seconds),
        "prior_half_marathon_best_seconds": _optional_csv_value(
            row.prior_half_marathon_best_seconds
        ),
        "prior_marathon_best_seconds": _optional_csv_value(row.prior_marathon_best_seconds),
    }
    for window in row.training_windows:
        prefix = f"prior_{window.days}d_"
        values.update(
            {
                f"{prefix}runs": window.runs,
                f"{prefix}distance_km": window.distance_km,
                f"{prefix}moving_hours": window.moving_hours,
                f"{prefix}longest_run_km": _optional_csv_value(window.longest_run_km),
                f"{prefix}weighted_pace_seconds_per_km": (
                    _optional_csv_value(window.weighted_pace_seconds_per_km)
                ),
                f"{prefix}elevation_gain_m": _optional_csv_value(window.elevation_gain_m),
                f"{prefix}activities_with_heart_rate": (window.activities_with_heart_rate),
                f"{prefix}duration_load_minutes": window.duration_load_minutes,
            }
        )
    return values


def _write_dataset(path: Path, dataset: PerformanceTrainingDataset) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=_fieldnames())
        writer.writeheader()
        writer.writerows(
            _csv_row(row, dataset_version=dataset.dataset_version) for row in dataset.rows
        )


def main(arguments: list[str] | None = None) -> int:
    """Build the review dataset and write it only inside private storage."""

    parser = _build_parser()
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    athlete_id = parsed.athlete_id or settings.athlete_id
    if athlete_id is None:
        parser.error("Provide --athlete-id or configure RUNCOACH_ATHLETE_ID.")

    try:
        output_path = _private_output_path(parsed.output, settings.private_data_dir)
    except ValueError as error:
        parser.error(str(error))

    with SessionFactory() as session:
        dataset = PerformanceAuditQueryService(session).training_dataset(
            athlete_id=athlete_id,
            distance_tolerance_pct=parsed.distance_tolerance_pct,
        )

    _write_dataset(output_path, dataset)
    print(
        json.dumps(
            {
                "dataset_version": dataset.dataset_version,
                "output": str(output_path),
                "candidate_rows": dataset.candidate_rows,
                "verified_rows": dataset.verified_rows,
                "unreviewed_rows": dataset.unreviewed_rows,
                "model_status": dataset.model_status,
                "leakage_rule": dataset.leakage_rule,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
