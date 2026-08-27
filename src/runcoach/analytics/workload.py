"""Deterministic daily workload and fitness-fatigue indicators."""

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import Final

DAILY_LOAD_ALGORITHM_VERSION: Final = "daily_load_v1"
ACUTE_TIME_CONSTANT_DAYS: Final = 7
CHRONIC_TIME_CONSTANT_DAYS: Final = 42


@dataclass(frozen=True, slots=True)
class DailyLoadObservation:
    """Aggregated activity load observed on one local date."""

    local_date: date
    daily_load: float
    coverage_pct: float = 100.0

    def __post_init__(self) -> None:
        if not isfinite(self.daily_load) or self.daily_load < 0:
            raise ValueError("Daily load must be finite and non-negative.")

        if not isfinite(self.coverage_pct) or not 0 <= self.coverage_pct <= 100:
            raise ValueError("Coverage must be between zero and 100.")


@dataclass(frozen=True, slots=True)
class DailyLoadResult:
    """One continuous daily workload state."""

    local_date: date
    algorithm_version: str
    daily_load: float
    acute_load: float | None
    chronic_load: float | None
    fitness_index: float | None
    fatigue_index: float | None
    form_index: float | None
    coverage_pct: float
    history_days: int


def _next_exponential_state(
    previous_state: float,
    daily_load: float,
    time_constant_days: int,
) -> float:
    return previous_state + ((daily_load - previous_state) / time_constant_days)


def calculate_daily_load_series(
    observations: tuple[DailyLoadObservation, ...],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[DailyLoadResult, ...]:
    """Calculate a gap-free daily series including zero-load rest days."""

    if not observations:
        if start_date is not None or end_date is not None:
            raise ValueError("A date range cannot be calculated without observations.")
        return ()

    observation_dates = tuple(observation.local_date for observation in observations)
    if len(set(observation_dates)) != len(observation_dates):
        raise ValueError("Daily load observations must have unique dates.")

    if observation_dates != tuple(sorted(observation_dates)):
        raise ValueError("Daily load observations must be ordered chronologically.")

    first_observation_date = observation_dates[0]
    last_observation_date = observation_dates[-1]
    series_start = start_date or first_observation_date
    series_end = end_date or last_observation_date

    if series_start > first_observation_date:
        raise ValueError("Series start cannot be later than the first observation.")

    if series_end < last_observation_date:
        raise ValueError("Series end cannot be earlier than the last observation.")

    if series_start > series_end:
        raise ValueError("Series start must not be later than series end.")

    observations_by_date = {observation.local_date: observation for observation in observations}

    results: list[DailyLoadResult] = []
    acute_state = 0.0
    chronic_state = 0.0
    current_date = series_start
    history_days = 0

    while current_date <= series_end:
        observation = observations_by_date.get(current_date)
        daily_load = observation.daily_load if observation is not None else 0.0
        coverage_pct = observation.coverage_pct if observation is not None else 100.0

        history_days += 1
        acute_state = _next_exponential_state(
            acute_state,
            daily_load,
            ACUTE_TIME_CONSTANT_DAYS,
        )
        chronic_state = _next_exponential_state(
            chronic_state,
            daily_load,
            CHRONIC_TIME_CONSTANT_DAYS,
        )

        acute_load = round(acute_state, 6) if history_days >= ACUTE_TIME_CONSTANT_DAYS else None
        chronic_load = (
            round(chronic_state, 6) if history_days >= CHRONIC_TIME_CONSTANT_DAYS else None
        )
        form_index = (
            round(chronic_state - acute_state, 6)
            if acute_load is not None and chronic_load is not None
            else None
        )

        results.append(
            DailyLoadResult(
                local_date=current_date,
                algorithm_version=DAILY_LOAD_ALGORITHM_VERSION,
                daily_load=round(daily_load, 6),
                acute_load=acute_load,
                chronic_load=chronic_load,
                fitness_index=chronic_load,
                fatigue_index=acute_load,
                form_index=form_index,
                coverage_pct=round(coverage_pct, 4),
                history_days=history_days,
            )
        )
        current_date += timedelta(days=1)

    return tuple(results)
