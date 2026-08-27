# RunCoach AI

RunCoach AI is an AI-powered running performance and coaching platform that transforms
Garmin and Strava exports into validated activity history, deterministic training analytics,
performance models, and evidence-backed coaching recommendations.

The project combines data engineering, applied machine learning, cloud computing, software
architecture, and controlled AI-agent orchestration. It applies Big Data engineering
principles without claiming to operate at genuine Big Data scale.

> Project status: activity ingestion, reconciliation, sensor storage, and deterministic
> workload analytics are operational.

## Problem

An athlete's history can be fragmented across platforms, formats, sensor coverage, and time
periods. Provider dashboards also expose results without always providing reproducible
methodology, source provenance, or controlled integration with personalized coaching logic.

RunCoach AI creates a reproducible pipeline that:

- Imports exported Garmin and Strava data.
- Validates and normalizes heterogeneous records.
- Reconciles cross-source duplicates.
- Preserves file, record, and field provenance.
- Stores canonical activities, laps, and sensor observations.
- Calculates deterministic, versioned training metrics.
- Evaluates performance and race readiness.
- Produces explainable recommendations from validated evidence.

The system is a coaching-support and research platform. It does not provide medical
diagnoses or guarantee race outcomes.

## Product scope

The target platform includes:

- A single-athlete profile with an `athlete_id` retained for future multi-athlete support.
- Garmin and Strava export ingestion through FIT, FIT.GZ, GPX, CSV, and JSON adapters.
- Validation, normalization, provenance tracking, and cross-source deduplication.
- PostgreSQL storage for activities, laps, trackpoints, derived metrics, and model outputs.
- Deterministic workload, fitness, fatigue, form, personal-best, and race-readiness analysis.
- A deterministic Riegel race-time baseline.
- A machine-learning experiment selected after auditing the available labels.
- A Streamlit analytical interface backed by a FastAPI API.
- A controlled LangGraph coaching workflow that interprets validated evidence.
- Dockerized execution, automated tests, CI, and a sanitized cloud demonstration.

## Current implementation

The operational data pipeline currently provides:

- Positional parsing of Strava's duplicate-header activity CSV.
- Garmin summary JSON parsing.
- FIT, compressed FIT, and namespace-aware GPX parsing.
- Conservative cross-source activity reconciliation.
- Transactional and idempotent PostgreSQL persistence.
- Canonical source selection with Garmin preferred for overlapping recent sensor data.
- Storage of normalized laps and trackpoints.
- Time-valid physiology profiles.
- Per-activity pace and sensor-coverage calculations.
- Maximum-heart-rate zone distribution.
- Edwards TRIMP when sufficient heart-rate evidence exists.
- Full-history duration workload.
- Gap-free daily acute, chronic, fitness, fatigue, and form series.
- Versioned input hashing and reproducible recalculation.

## Architecture

The project uses a modular monolith: one Python codebase with explicit domain modules and
separate API, batch-processing, and user-interface runtime processes where justified.
PostgreSQL is the durable system of record.

Additional distributed components are adopted only when measured requirements demonstrate a
clear data-volume, scaling, resilience, deployment, or integration benefit.

See [Architecture](docs/architecture.md) and [Data model](docs/data-model.md).

## Scientific guardrails

- Training metrics are calculated by deterministic, versioned code.
- The language model does not calculate pace, workload, heart-rate zones, race predictions,
  or readiness scores.
- Fitness, fatigue, form, and readiness are modeled indicators rather than direct
  physiological measurements.
- Workload changes may produce non-medical warning indicators but never injury diagnoses.
- Machine-learning results must be evaluated chronologically against deterministic
  baselines.
- Missing data is represented explicitly.
- Insufficient evidence must be reported rather than presented as statistical validity.

## Privacy and security

Raw Garmin and Strava exports are private and must never be committed to Git.

- Secrets belong in `.env`, which is ignored.
- Shareable configuration belongs in `.env.example`.
- Raw files belong only in ignored local data directories.
- Sanitized fixtures must contain no identifying GPS routes, names, account identifiers, or
  credentials.
- Cloud demonstrations use sanitized or synthetic data.
- Raw GPS coordinates are not sent to an LLM by default.
- Analytics input hashes use position availability rather than raw coordinates.

## Local development

Prerequisites:

- Python 3.12
- `uv`
- Git
- Docker Desktop with Docker Compose

Initialize the local environment:

```powershell
Copy-Item '.env.example' '.env'
uv sync --all-groups
docker compose up -d db
uv run alembic upgrade head
```

Run the API:

```powershell
uv run uvicorn runcoach.main:app --reload
```

Verify readiness:

```powershell
Invoke-RestMethod 'http://localhost:8000/health/ready'
```

## Private data import

Set one stable `RUNCOACH_ATHLETE_ID` UUID in the ignored `.env` file before importing data.

Import and reconcile activity summaries:

```powershell
uv run python -m runcoach.cli.import_summaries `
  --timezone 'Africa/Casablanca' `
  --strava-csv 'data\private\strava\extracted\activities.csv' `
  --garmin-json 'data\private\garmin\extracted\path\to\summarizedActivities.json'
```

Import raw Strava activity detail:

```powershell
uv run python -m runcoach.cli.import_sensors `
  --strava-root 'data\private\strava\extracted'
```

Import raw Garmin activity detail:

```powershell
uv run python -m runcoach.cli.import_sensors `
  --garmin-root 'data\private\garmin\extracted' `
  --progress-every 500
```

Raw imports use checksums and source identifiers for idempotence. Garmin FIT is preferred for
recent overlapping runs, while Strava FIT, FIT.GZ, and GPX provide historical coverage and
fallback data.

## Physiology configuration

Configure only observed or formally tested values. Unknown values should be omitted.

The following variables are examples and must be replaced with verified athlete evidence:

```powershell
$profileStartDate = '2026-01-01'
$observedMaxHr = 190
$restingHr = 50

uv run python -m runcoach.cli.configure_profile `
  --valid-from $profileStartDate `
  --observed-max-hr $observedMaxHr `
  --resting-hr $restingHr `
  --notes 'Observed values; threshold heart rate not formally tested.'
```

Profiles are time-valid. A new observation period must not silently overwrite historical
calculation inputs.

## Deterministic analytics

Calculate versioned activity and daily workload metrics through an explicit local date:

```powershell
$asOfDate = Get-Date -Format 'yyyy-MM-dd'

uv run python -m runcoach.cli.calculate_analytics `
  --as-of-date $asOfDate
```

Re-running the command with unchanged inputs reuses existing activity metrics and daily-load
rows.

The initial longitudinal workload method uses effective running duration because it is
available across the historical dataset. Edwards TRIMP is retained separately for activities
with adequate heart-rate coverage.

See [Deterministic analytics methodology](docs/analytics-methodology.md).

## Analytics API

The read-only analytics API exposes persisted deterministic results:

```text
GET /api/v1/analytics/overview
```

Omitting `as_of_date` returns the latest calculated workload snapshot. An exact historical
snapshot can be requested with:

```text
GET /api/v1/analytics/overview?as_of_date=2026-08-27
```

Example PowerShell request:

```powershell
Invoke-RestMethod 'http://localhost:8000/api/v1/analytics/overview' |
  ConvertTo-Json -Depth 8
```

The response includes:

- Full-history run count, distance, and moving time
- Seven-day and 28-day training summaries
- Aggregate heart-rate, GPS, and cadence coverage
- Latest daily, acute, chronic, fitness, fatigue, and form values
- Calculation method and algorithm versions

The endpoint does not expose the athlete UUID, source identifiers, filenames, or raw route
coordinates.

## Quality checks

Run the complete local verification suite:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=runcoach --cov-report=term-missing
uv run alembic check
docker compose config --quiet
```

## Documentation

- [Problem statement](docs/problem-statement.md)
- [Requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Data source audit](docs/data-source-audit.md)
- [Deterministic analytics methodology](docs/analytics-methodology.md)
- [Machine-learning methodology](docs/ml-methodology.md)
- [Agent workflow](docs/agent-workflow.md)
- [Testing strategy](docs/testing-strategy.md)
- [Deployment](docs/deployment.md)
- [Experiment log](docs/experiment-log.md)
- [Assumptions and limitations](docs/assumptions-and-limitations.md)
- [Report notes](docs/report-notes.md)
- [Presentation outline](docs/presentation-outline.md)