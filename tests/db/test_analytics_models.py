"""Schema-contract tests for deterministic analytics persistence."""

from typing import cast

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from runcoach.db.models import (
    ActivityMetric,
    DailyLoad,
    PhysiologyProfile,
)


def _unique_column_sets(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_constraint_names(table: Table) -> set[str]:
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def test_physiology_profile_has_time_validity_and_athlete_identity() -> None:
    table = cast(Table, PhysiologyProfile.__table__)

    assert table.name == "physiology_profiles"
    assert ("athlete_id", "valid_from") in _unique_column_sets(table)
    assert {
        "physiology_profiles_valid_period",
        "physiology_profiles_max_hr",
        "physiology_profiles_resting_hr",
        "physiology_profiles_threshold_hr",
        "physiology_profiles_threshold_pace",
    } <= _check_constraint_names(table)

    athlete_foreign_key = next(iter(table.c.athlete_id.foreign_keys))
    assert athlete_foreign_key.target_fullname == "athletes.id"
    assert athlete_foreign_key.ondelete == "CASCADE"


def test_activity_metric_has_versioned_idempotency_key() -> None:
    table = cast(Table, ActivityMetric.__table__)

    assert table.name == "activity_metrics"
    assert (
        "activity_id",
        "algorithm_version",
        "input_hash",
    ) in _unique_column_sets(table)
    assert {
        "activity_metrics_hr_coverage",
        "activity_metrics_gps_coverage",
        "activity_metrics_cadence_coverage",
        "activity_metrics_training_load",
        "activity_metrics_input_hash",
    } <= _check_constraint_names(table)

    activity_foreign_key = next(iter(table.c.activity_id.foreign_keys))
    assert activity_foreign_key.target_fullname == "activities.id"
    assert activity_foreign_key.ondelete == "CASCADE"

    profile_foreign_key = next(iter(table.c.profile_id.foreign_keys))
    assert profile_foreign_key.target_fullname == "physiology_profiles.id"
    assert profile_foreign_key.ondelete == "SET NULL"


def test_daily_load_separates_methods_and_algorithm_versions() -> None:
    table = cast(Table, DailyLoad.__table__)

    assert table.name == "daily_loads"
    assert (
        "athlete_id",
        "local_date",
        "load_method",
        "algorithm_version",
    ) in _unique_column_sets(table)
    assert {
        "daily_loads_daily_load",
        "daily_loads_acute_load",
        "daily_loads_chronic_load",
        "daily_loads_fitness_index",
        "daily_loads_fatigue_index",
        "daily_loads_coverage",
    } <= _check_constraint_names(table)


def test_analytics_json_fields_remain_source_neutral() -> None:
    table = cast(Table, ActivityMetric.__table__)

    assert table.c.zone_distribution.nullable is False
    assert table.c.additional_metrics.nullable is False
    assert table.c.zone_distribution.default is not None
    assert table.c.additional_metrics.default is not None
