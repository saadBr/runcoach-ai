"""Golden tests for deterministic daily workload indicators."""

from datetime import date, timedelta

import pytest

from runcoach.analytics.workload import (
    ACUTE_TIME_CONSTANT_DAYS,
    CHRONIC_TIME_CONSTANT_DAYS,
    DAILY_LOAD_ALGORITHM_VERSION,
    DailyLoadObservation,
    calculate_daily_load_series,
)


def test_empty_observations_produce_an_empty_series() -> None:
    assert calculate_daily_load_series(()) == ()


def test_missing_dates_are_filled_as_rest_days() -> None:
    observations = (
        DailyLoadObservation(
            local_date=date(2026, 1, 1),
            daily_load=70,
            coverage_pct=80,
        ),
        DailyLoadObservation(
            local_date=date(2026, 1, 3),
            daily_load=35,
            coverage_pct=50,
        ),
    )

    results = calculate_daily_load_series(observations)

    assert len(results) == 3
    assert results[0].local_date == date(2026, 1, 1)
    assert results[0].daily_load == 70
    assert results[0].coverage_pct == 80

    assert results[1].local_date == date(2026, 1, 2)
    assert results[1].daily_load == 0
    assert results[1].coverage_pct == 100

    assert results[2].local_date == date(2026, 1, 3)
    assert results[2].daily_load == 35
    assert results[2].coverage_pct == 50

    assert all(result.acute_load is None for result in results)
    assert all(result.chronic_load is None for result in results)


def test_constant_load_matches_exponential_recurrence() -> None:
    start = date(2026, 1, 1)
    daily_load = 70.0
    observations = tuple(
        DailyLoadObservation(
            local_date=start + timedelta(days=offset),
            daily_load=daily_load,
        )
        for offset in range(CHRONIC_TIME_CONSTANT_DAYS)
    )

    results = calculate_daily_load_series(observations)

    expected_acute = daily_load * (
        1 - (1 - (1 / ACUTE_TIME_CONSTANT_DAYS)) ** CHRONIC_TIME_CONSTANT_DAYS
    )
    expected_chronic = daily_load * (
        1 - (1 - (1 / CHRONIC_TIME_CONSTANT_DAYS)) ** CHRONIC_TIME_CONSTANT_DAYS
    )

    assert results[5].acute_load is None
    assert results[6].acute_load is not None
    assert results[40].chronic_load is None

    final = results[-1]
    assert final.algorithm_version == DAILY_LOAD_ALGORITHM_VERSION
    assert final.history_days == CHRONIC_TIME_CONSTANT_DAYS
    assert final.acute_load == pytest.approx(expected_acute, abs=0.000001)
    assert final.chronic_load == pytest.approx(
        expected_chronic,
        abs=0.000001,
    )
    assert final.fatigue_index == final.acute_load
    assert final.fitness_index == final.chronic_load
    assert final.form_index == pytest.approx(
        expected_chronic - expected_acute,
        abs=0.000001,
    )


def test_explicit_start_date_includes_pre_observation_rest_days() -> None:
    observation_date = date(2026, 1, 3)
    results = calculate_daily_load_series(
        (
            DailyLoadObservation(
                local_date=observation_date,
                daily_load=60,
            ),
        ),
        start_date=date(2026, 1, 1),
    )

    assert len(results) == 3
    assert [result.daily_load for result in results] == [0, 0, 60]
    assert [result.history_days for result in results] == [1, 2, 3]


def test_explicit_end_date_includes_future_rest_days() -> None:
    observation_date = date(2026, 1, 1)
    results = calculate_daily_load_series(
        (
            DailyLoadObservation(
                local_date=observation_date,
                daily_load=60,
            ),
        ),
        end_date=date(2026, 1, 3),
    )

    assert len(results) == 3
    assert [result.daily_load for result in results] == [60, 0, 0]


def test_rejects_duplicate_or_unordered_dates() -> None:
    duplicate_date = date(2026, 1, 1)

    with pytest.raises(ValueError, match="unique dates"):
        calculate_daily_load_series(
            (
                DailyLoadObservation(duplicate_date, 10),
                DailyLoadObservation(duplicate_date, 20),
            )
        )

    with pytest.raises(ValueError, match="chronologically"):
        calculate_daily_load_series(
            (
                DailyLoadObservation(date(2026, 1, 2), 10),
                DailyLoadObservation(date(2026, 1, 1), 20),
            )
        )


def test_rejects_invalid_ranges_and_values() -> None:
    observation = DailyLoadObservation(
        local_date=date(2026, 1, 2),
        daily_load=10,
    )

    with pytest.raises(ValueError, match="later than the first"):
        calculate_daily_load_series(
            (observation,),
            start_date=date(2026, 1, 3),
        )

    with pytest.raises(ValueError, match="earlier than the last"):
        calculate_daily_load_series(
            (observation,),
            end_date=date(2026, 1, 1),
        )

    with pytest.raises(ValueError, match="without observations"):
        calculate_daily_load_series(
            (),
            start_date=date(2026, 1, 1),
        )

    with pytest.raises(ValueError, match="Daily load"):
        DailyLoadObservation(
            local_date=date(2026, 1, 1),
            daily_load=-1,
        )

    with pytest.raises(ValueError, match="Coverage"):
        DailyLoadObservation(
            local_date=date(2026, 1, 1),
            daily_load=10,
            coverage_pct=101,
        )
