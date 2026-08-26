# RunCoach AI

RunCoach AI is a Master's graduation project for analyzing running activities, modeling
training and performance trends, estimating race readiness, and generating evidence-backed
coaching recommendations.

The project demonstrates data-engineering, machine-learning, cloud-computing, software
architecture, and controlled AI-agent concepts without claiming to operate at genuine Big
Data scale.

> Project status: Milestone 1A - architecture baseline and executable project foundation.

## Problem

Garmin and Strava provide useful activity records, but an athlete's history can be fragmented
across platforms, file formats, sensor coverage, and time periods. RunCoach AI will create a
reproducible pipeline that imports exported activity files, validates and normalizes them,
calculates deterministic training metrics, evaluates performance trends, and explains
recommendations.

The system is a coaching-support and research prototype. It does not provide medical
diagnoses or guarantee race outcomes.

## MVP scope

The planned MVP includes:

- A single-athlete profile with an `athlete_id` retained in the data model.
- Garmin and Strava export ingestion through inspected FIT, GPX, CSV, and bulk-export
  adapters.
- Validation, normalization, provenance tracking, and cross-source deduplication.
- PostgreSQL storage for activities, laps, trackpoints, and derived metrics.
- Deterministic workload, fitness, fatigue, form, personal-best, and race-readiness analysis.
- A deterministic Riegel race-time baseline.
- One machine-learning experiment selected only after auditing the available labels.
- A Streamlit dashboard backed by a FastAPI API.
- A controlled LangGraph coaching workflow that interprets validated evidence.
- Dockerized local execution, automated tests, CI, and a sanitized cloud demonstration.

## Architecture

The project uses a modular monolith: one Python codebase with explicit domain modules and
separate API, import-worker, and UI runtime processes where justified. PostgreSQL is the
durable system of record.

Kafka, Kubernetes, microservices, NoSQL, RAG, and a custom JavaScript frontend are excluded
from the MVP unless later evidence demonstrates that they solve a necessary problem within
the project schedule.

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
- Insufficient data must be reported instead of hidden or presented as statistical validity.

## Privacy and security

Raw Garmin and Strava exports are private and must never be committed to Git.

- Secrets belong in `.env`, which is ignored.
- Shareable configuration belongs in `.env.example`.
- Raw files belong only in ignored local data directories.
- Sanitized test fixtures must contain no identifying GPS routes, names, account identifiers,
  or credentials.
- The cloud demonstration will use sanitized or synthetic data.
- Raw GPS tracks are not sent to an LLM by default.

## Planned local development

Prerequisites:

- Python 3.12
- `uv`
- Git
- Docker Desktop with Docker Compose

After Milestone 1A is complete, the expected PowerShell workflow will be:

```powershell
Copy-Item '.env.example' '.env'
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
docker compose up --build -d
Invoke-RestMethod 'http://localhost:8000/health/ready'

```
## Private data import

Set `RUNCOACH_ATHLETE_ID` in the ignored `.env` file and apply the database migrations:

```powershell
uv run alembic upgrade head
```

Import and reconcile activity summaries:

```powershell
uv run python -m runcoach.cli.import_summaries `
  --timezone 'Africa/Casablanca' `
  --strava-csv 'data\private\strava\extracted\activities.csv' `
  --garmin-json 'data\private\garmin\extracted\path\to\summarizedActivities.json'
```

Import raw Strava and Garmin activity detail:

```powershell
uv run python -m runcoach.cli.import_sensors `
  --strava-root 'data\private\strava\extracted'

uv run python -m runcoach.cli.import_sensors `
  --garmin-root 'data\private\garmin\extracted' `
  --progress-every 500
```

Raw imports use checksums and source identifiers for idempotence. Garmin FIT is preferred for
recent overlapping runs, while Strava FIT, FIT.GZ, and GPX files provide historical coverage
and fallback data. Raw files and GPS coordinates remain in ignored local storage and the
private PostgreSQL database.
## Documentation

- [Problem statement](docs/problem-statement.md)
- [Requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Data source audit](docs/data-source-audit.md)
- [Machine-learning methodology](docs/ml-methodology.md)
- [Agent workflow](docs/agent-workflow.md)
- [Testing strategy](docs/testing-strategy.md)
- [Deployment](docs/deployment.md)
- [Experiment log](docs/experiment-log.md)
- [Assumptions and limitations](docs/assumptions-and-limitations.md)
- [Report notes](docs/report-notes.md)
- [Presentation outline](docs/presentation-outline.md)