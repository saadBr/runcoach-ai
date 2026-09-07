# RunCoach AI

RunCoach AI is an AI-powered running performance and coaching platform that transforms
Garmin and Strava exports into validated activity history, deterministic training analytics,
performance models, and evidence-backed coaching recommendations.

The project combines data engineering, applied machine learning, cloud computing, software
architecture, and controlled AI-agent orchestration. It applies Big Data engineering
principles without claiming to operate at genuine Big Data scale.

> Project status: activity ingestion, reconciliation, sensor storage, deterministic
> analytics and performance baselines, read-only APIs, and the containerized dashboard are
> operational.

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

- Athlete-scoped profiles with a compatibility path for the original local single-athlete mode.
- Garmin and Strava export ingestion through FIT, FIT.GZ, GPX, CSV, and JSON adapters.
- Validation, normalization, provenance tracking, and cross-source deduplication.
- PostgreSQL storage for activities, laps, trackpoints, derived metrics, and model outputs.
- Deterministic workload, fitness, fatigue, form, personal-best, and race-readiness analysis.
- A deterministic Riegel benchmark retained for model evaluation, not user-facing forecasting.
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
- Read-only overview and longitudinal-trends API endpoints.
- Verified standard-distance personal-best history with auditable evidence links.
- A leakage-safe private export for reviewing candidate performance labels and training features.
- A validated Streamlit dashboard with interactive Plotly visualizations.
- An evidence-grounded conversational coach with cited facts, deterministic safety review, and
  a useful provider-disabled fallback.
- Durable minimized audit records for every successful coaching answer, including ordered
  evidence, generation, safety-review steps, and the approved or fallback recommendation.
- Multi-athlete signup with one-to-one accounts, revocable opaque sessions, a required bounded
  Strava ZIP import, resumable onboarding, and separate optional research-consent history.
- Operational account login, session inspection, logout, and authenticated athlete ownership
  across private analytics and coaching endpoints.
- An optional stateless OpenAI Responses API adapter with schema-constrained output; numeric
  predictions and training prescriptions remain owned by versioned RunCoach code.
- Independent, health-checked API, dashboard, and PostgreSQL Compose services.

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

### Preserve and claim an existing local athlete

The authenticated onboarding migration does not delete or replace an existing athlete. After
applying migrations, attach an account to the athlete already identified by
`RUNCOACH_ATHLETE_ID` with:

```powershell
uv run python -m runcoach.cli.bootstrap_account --display-name 'Your display name'
```

The command prompts for email and password interactively so credentials do not appear in shell
history. It verifies that the existing athlete already has an accepted Strava import, exactly one
active primary goal, and exactly one active plan. It then creates the account and marks onboarding
ready while preserving the athlete UUID, activities, analytics, personal bests, goal, and plan.
The optional display name fills an empty existing value but never silently replaces a different
name. Running it again with the same credentials is idempotent. It does not grant model-research
consent.

### Create a new athlete account

Choose **Create account** on the dashboard. Registration requires a future race goal, one known
Strava benchmark effort, and the original Strava account-export ZIP. The account remains pending
until the ZIP produces at least 10 running activities, the declared benchmark date matches one
eligible run, deterministic analytics are calculated, and the first plan is persisted. A failed
or interrupted import can be retried after signing in; private analytics remain inaccessible
until onboarding reaches `ready`.

The API validates every ZIP member before selectively extracting `activities.csv` and supported
FIT, FIT.GZ, or GPX activity files into short-lived private storage. It rejects traversal paths,
links, encrypted entries, duplicate paths, unsupported compression, and bounded-size violations.
The uploaded archive and extracted files are deleted after the request. When only one verified
benchmark exists, missing race distances receive a disclosed low-confidence cross-distance
baseline until the athlete records direct evidence at those distances.

Run the API:

```powershell
uv run uvicorn runcoach.main:app --reload
```

Verify readiness:

```powershell
Invoke-RestMethod 'http://localhost:8000/health/ready'
```

### Login and authenticated API access

The dashboard now opens on a login page and displays the linked athlete name after successful
authentication. It keeps the opaque bearer token only in Streamlit session memory and revokes it
on sign-out. The API stores only the token's SHA-256 hash. Private analytics, plans, run uploads,
and coaching derive `athlete_id` from that session; the browser does not supply an athlete ID.

For direct PowerShell API calls, open a session without placing the password in shell history:

```powershell
$credentials = Get-Credential
$loginBody = @{
  email = $credentials.UserName
  password = $credentials.GetNetworkCredential().Password
} | ConvertTo-Json
$login = Invoke-RestMethod `
  -Method Post `
  -Uri 'http://localhost:8000/api/v1/auth/login' `
  -ContentType 'application/json' `
  -Body $loginBody
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

`GET /api/v1/auth/me` returns only display name, timezone, onboarding status, and session expiry.
`GET /api/v1/auth/onboarding` allows a pending session to resume its required ZIP upload.
`POST /api/v1/auth/logout` revokes the current token. Health endpoints remain unauthenticated.

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

Import standalone Strava FIT downloads created after the bulk export:

```powershell
uv run python -m runcoach.cli.import_strava_activities `
  --activity-dir 'data\private\strava\extracted\activities' `
  --since '2026-08-24'
```

This incremental command discovers FIT and FIT.GZ files directly because they are not listed
in the older `activities.csv`. It creates missing canonical runs, derives a provisional title
from the downloaded Strava filename, stores laps and trackpoints in the same transaction, and
uses file hashes plus activity matching to make repeat imports idempotent. Windows download
suffixes such as `(1)` are not treated as part of the activity title.

For routine updates after the initial import, place newly downloaded Strava FIT files in the
ignored activities directory and run the complete coaching update:

```powershell
uv run python -m runcoach.cli.update_coaching
```

The command skips already imported hashes before parsing, imports unseen running files,
recalculates analytics through the latest canonical run, and returns the current session match,
weekly adherence, and coaching recommendation as JSON. A meaningful filename such as
`3x3K_Threshold_Session.fit` or `Progressive_Long_Run.fit` should be assigned before the first
import because the provisional session title is derived from that filename. Use `--since`
only when intentionally limiting discovery to a local-date boundary.

The detailed schedule remains stable during its active week. The updater does not regenerate
the plan after every run; it rolls the plan forward after the final dated session in the
detailed week, retaining the previous recommendation in the update result for auditability.

The dashboard provides the primary day-to-day path: under **Add a Strava run**, select one
`.fit` or `.fit.gz` download, edit its title, and choose **Upload and update coaching**. The
dashboard sends the binary payload to FastAPI; the API streams it into short-lived private
storage, validates and parses exactly one running activity, imports it idempotently, refreshes
deterministic analytics, and returns the current plan match and recommendation. The staged file
is deleted after processing. The CLI remains available for bulk recovery and automation.

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
Invoke-RestMethod -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/analytics/overview' |
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

### Training trends

The trends endpoint returns calendar-week training summaries and the corresponding daily
workload series:

```powershell
Invoke-RestMethod `
  -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/analytics/trends?weeks=12'
```

Optional query parameters:

- `weeks`: Number of calendar weeks from 1 through 52; defaults to 12.
- `end_date`: Exact calculated workload date in `YYYY-MM-DD` format; defaults to the latest
  available workload date.

Weekly results include run count, distance, moving time, duration load, weighted average
pace, elevation gain, heart-rate load coverage, and Edwards TRIMP when available. Empty
calendar weeks are retained so charts preserve the time axis.

The endpoint exposes calculated aggregates only. It does not return athlete identifiers,
private filenames, source identifiers, or raw GPS coordinates.

### Verified performance

The performance endpoint returns current verified 5K, 10K, half-marathon, and marathon
personal bests together with a versioned experimental current-fitness estimate:

```powershell
Invoke-RestMethod -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/analytics/performance' |
  ConvertTo-Json -Depth 8
```

Each personal best includes its activity and evidence identifiers, verification status,
effort type, source, and algorithm version. `training_context_fitness_v3` distinguishes
flat-course fitness potential from distance-specific race readiness. It recognizes when the
newest verified effort is embedded inside a longer quality session, transfers improvement
through the athlete's own PB relationships, and compares current training with the training
before each PB. Readiness then uses recent frequency, volume, and longest-run support. The
response includes both times, an uncertainty range, preparation score, confidence, and
calculation evidence. The estimator remains experimental until evaluated chronologically;
the Riegel formula remains only a comparison benchmark.

For every supported distance, the estimator searches a bounded set of the fastest relevant
activities and calculates the fastest exact-distance effort from cumulative Strava sensor
samples. When that observed effort is faster than the athlete-confirmed PB—or fills a missing
distance—it bounds the forecast so the application cannot predict a time slower than performance
already present in the imported history. It remains low-confidence evidence until the athlete
confirms it.

Trackpoint evidence can recover exact-distance efforts inside longer sessions, including
warm-up and cool-down workouts. The evidence query reports both the first crossing from the
activity start and the fastest rolling segment, using versioned linear interpolation between
cumulative-distance samples. Provider-verified best-effort times remain the authoritative
stored labels; the derived segment is supporting evidence rather than a replacement measurement.

Export the private performance-review dataset with:

```powershell
uv run python -m runcoach.cli.export_performance_dataset
```

The CSV is written to `data/private/ml/performance-label-audit.csv`. It contains candidate
activity names and identifiers, so the CLI refuses destinations outside the configured
private-data directory. Each row includes 7-, 28-, 42-, 84-, 180-, and 365-day training
volume, pace, elevation, heart-rate availability, duration load, explainable title-derived
session counts, prior workload state, and prior verified PB evidence. All features stop
strictly before the candidate starts; unreviewed candidates have no verified target time.

Run leakage-safe chronological baseline validation against that frozen audit export with:

```powershell
uv run python -m runcoach.cli.validate_performance_predictions
```

The command writes detailed predictions to the ignored private artifact
`data/private/ml/performance-validation.json` and prints only aggregate errors and eligibility
reasons. It evaluates best-prior Riegel, most-recent same-distance, and historical-median
same-distance baselines. A target can use only manually verified performances with strictly
earlier timestamps. Results remain descriptive until the predeclared label-count and
chronological-evaluation gates pass.

The local dashboard also exposes a one-at-a-time **Improve prediction accuracy** reviewer.
Each decision marks a candidate as a verified race, time trial, maximum effort, or excluded
training effort; verified times may be corrected to an official result. Saving rewrites the
ignored CSV atomically and immediately refreshes the chronological validation artifact. A
fresh dataset export preserves existing manual decisions. The API returns only an opaque review
token, date, distance, time, and derived session class for this workflow—never the activity UUID
or private title—and the review endpoints are unavailable when the application environment is
`production`.

### Training-plan preview

The coaching API can assess a selected race goal and generate a progressive plan preview:

```powershell
Invoke-RestMethod -Headers $headers -Uri (
  'http://localhost:8000/api/v1/coaching/plan-preview?' +
  'distance=marathon&race_date=2027-01-31&' +
  'target_time_seconds=11400&days_per_week=6'
) | ConvertTo-Json -Depth 8
```

`goal_plan_preview_v2` uses the current training-context fitness estimate, trailing 28-day
volume, target-specific preparation, and the time remaining before race day. It reports goal
status, the first week as concrete dated sessions, and a full week-by-week volume and focus
outline. Build weeks progress gradually, every fourth week reduces load, and the final weeks
taper. It preserves recent volume when runs are consolidated into fewer days, builds toward a
distance-specific peak when the race horizon safely permits it, and avoids meaningless filler
runs in the first week. The preview endpoint is read-only until the athlete explicitly saves it
as the active plan.

Persist the selected goal and plan, retrieve it later, or refresh it after importing new
activities:

```powershell
Invoke-RestMethod -Method Post -Headers $headers -Uri (
  'http://localhost:8000/api/v1/coaching/plans/active?' +
  'distance=marathon&race_date=2027-01-31&' +
  'target_time_seconds=11400&days_per_week=6'
)
Invoke-RestMethod -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/coaching/plans/active'
Invoke-RestMethod -Method Post -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/coaching/plans/active/refresh'
Invoke-RestMethod -Headers $headers `
  -Uri 'http://localhost:8000/api/v1/coaching/plans/active/tracking'
```

Identical evidence reuses the active version. Changed fitness or training evidence creates a
new plan version and retains the previous snapshot as superseded history. The tracking
endpoint compares canonical running distance and the longest run with each planned week,
reports plan-to-date adherence, matches first-week prescriptions to imported activities, and
exposes the evidence and load targets for every version. Detailed-week adherence follows the
scheduled sessions due to date, allows a small absolute volume tolerance, and treats a slower
easy or recovery run as easier rather than failed. Missed quality work is never moved onto the
following day by the coaching recommendation.

## Analytical dashboard

Run the dashboard directly while the API is available at `http://localhost:8000`:

```powershell
uv run streamlit run src/runcoach/dashboard/app.py
```

The host dashboard uses `RUNCOACH_API_URL`, which defaults to `http://localhost:8000`.

Start the complete containerized platform with:

```powershell
docker compose up --build -d --wait
```

Local endpoints:

- Dashboard: `http://localhost:8501`
- FastAPI documentation: `http://localhost:8000/docs`
- API readiness: `http://localhost:8000/health/ready`

The dashboard consumes validated aggregate API responses. Its performance panel displays
verified personal bests and the experimental personalized estimates with ranges, confidence,
and multi-horizon training evidence. Its training-plan panel lets the athlete choose a race
distance, date, target time, and weekly running frequency, then displays the resulting goal
assessment, first training week, and complete progression outline. It currently preselects the
next marathon on 2027-01-31 and supports a rolling one-year goal horizon. The Coach panel answers
questions using minimized current-fitness, workload, goal, adherence, and upcoming-session
evidence. Each answer returns its evidence identifiers and limitations. OpenAI can explain this
evidence when configured, but numeric predictions and prescribed training loads remain outputs
of versioned, tested code. After a matched upload, questions such as `How did today's run go?`
produce a deterministic post-run debrief comparing actual distance and average pace with the
prescribed session before explaining the next plan action.

Successful coach responses are persisted as a minimized workflow audit. The database stores a
hash and length for the question rather than its raw text, the applicable context and prompt
versions, referenced evidence identifiers, three ordered workflow steps, limitations, and the
final recommendation. A response is not returned as successful when its audit transaction fails.

Conversational coaching works in deterministic mode by default. To enable the optional OpenAI
interpreter, set these values only in the ignored `.env` file and restart the API:

```dotenv
RUNCOACH_LLM_PROVIDER=openai
RUNCOACH_OPENAI_MODEL=gpt-5.4-mini
OPENAI_API_KEY=your-private-api-key
```

The API sends only the minimized coaching evidence contract and bounded recent conversation. It
uses schema-constrained output and disables provider-side response storage for these requests.
If configuration, connectivity, output validation, evidence review, or the provider fails, the
endpoint returns the deterministic evidence template instead of blocking coaching.

The same coach can be called directly:

```powershell
$body = @{
  message = 'What should I run next, and why?'
  conversation = @()
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri 'http://localhost:8000/api/v1/coaching/chat' `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $body
```

The upload control sends one selected binary file through the typed API and never mounts the
private activity directory in the dashboard container. The dashboard does not connect directly
to PostgreSQL or expose private filenames, credentials, or raw GPS coordinates in responses.

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
