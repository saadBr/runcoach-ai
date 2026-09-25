# AGENTS.md

## Purpose

PaceCraft AI is a Master's graduation project that analyzes exported Garmin and Strava
activities, calculates deterministic training and performance metrics, evaluates an
appropriately scoped machine-learning feature, and produces evidence-backed coaching
explanations.

All contributors and coding agents must preserve scientific honesty, privacy, reproducibility,
and the approved product scope and acceptance criteria.

## Working method

- Inspect existing files and Git status before changing anything.
- Work incrementally and stop at verified logical checkpoints.
- Never overwrite unrelated user changes.
- Explain important architectural decisions and tradeoffs.
- Add or update tests with each important behavior.
- Update relevant documentation in the same change as implementation.
- Diagnose failures before continuing.
- Recommend a Git commit only after the checkpoint is verified.
- Keep commits small, meaningful, and independently understandable.

## Architecture

- Use a Python 3.12 modular monolith.
- Keep domain modules explicit even though they share one repository and database.
- Use FastAPI for the HTTP API and Streamlit for the MVP interface.
- Use PostgreSQL through SQLAlchemy, with schema changes managed by Alembic.
- Use a database-backed import-job state machine instead of Kafka or Redis for the MVP.
- Keep file parsers behind adapter interfaces.
- Keep deterministic analytics independent from the UI and LLM provider.
- Add Kafka, Kubernetes, microservices, NoSQL, RAG, or another frontend only after a written
  architectural justification and explicit approval.

## Privacy and secrets

- Never commit raw Garmin or Strava exports.
- Never commit `.env`, API keys, tokens, credentials, or private database dumps.
- Raw files must stay under ignored private-data directories.
- Test fixtures must be synthetic or sanitized and contain no identifying GPS routes, names,
  account identifiers, or credentials.
- The public cloud demonstration must use sanitized or synthetic data.
- Do not send raw GPS tracks, credentials, or unnecessary personal fields to an LLM.
- Inspect staged files before every commit.

## Scientific and AI boundaries

- Calculate pace, heart-rate zones, workload, fitness, fatigue, form, personal bests,
  readiness components, and race baselines with deterministic code.
- Treat fitness, fatigue, form, readiness, and workload warnings as modeled indicators.
- Never present an injury warning as a diagnosis or a calibrated medical probability.
- Use the Riegel formula as the initial deterministic race-time baseline.
- Audit available labels before fixing the final machine-learning target.
- Use chronological evaluation and compare ML results with deterministic baselines.
- Report insufficient data or negative results honestly.
- The LLM may interpret validated evidence but must not invent measurements or replace
  deterministic calculations.
- Every generated recommendation must reference stored evidence and pass a safety review.

## Data engineering rules

- Preserve source provenance and parser versions.
- Store canonical units and UTC timestamps while retaining original timezone information.
- Make imports idempotent with checksums and source identifiers.
- Do not silently merge incompatible Garmin and Strava sensor streams.
- Record data coverage and the method used for every derived load metric.
- Version derived-metric algorithms and ML feature definitions.
- Do not claim genuine Big Data scale; describe the data-engineering principles actually used.

## Local commands

Run these commands from the repository root in PowerShell:

```powershell
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest --cov=runcoach --cov-report=term-missing
docker compose config --quiet
docker compose up --build -d
Invoke-RestMethod 'http://localhost:8000/health/ready'
docker compose down

## Testing expectations
- Unit-test deterministic calculations with known inputs and tolerances.
- Use sanitized parser fixtures and explicit malformed-file cases.
- Test import idempotency and cross-source deduplication.
- Use PostgreSQL for database integration tests rather than relying on SQLite equivalence.
- Test chronological ML splits for leakage.
- Test the coaching graph with a fake LLM provider.
- Test safety rejection and deterministic fallback behavior.
- Maintain at least 80 percent statement coverage unless a documented reason is approved.
## Documentation expectations
### Continuously maintain:
- README.md
- docs/problem-statement.md
- docs/requirements.md
- docs/architecture.md
- docs/data-model.md
- docs/ml-methodology.md
- docs/agent-workflow.md
- docs/testing-strategy.md
- docs/deployment.md
- docs/experiment-log.md
- docs/assumptions-and-limitations.md
- docs/report-notes.md
- docs/presentation-outline.md
Record major decisions under docs/adr/. Each technology decision must explain its purpose,
academic concept, simpler alternative, and limitations.
## Definition of done
A checkpoint is complete only when:
- Formatting, linting, strict type checking, and relevant tests pass.
- Database migrations and Docker configuration are validated when affected.
- No secret or private activity data is staged.
- Documentation reflects the implemented behavior.
- Git status and the staged diff contain only intended files.
