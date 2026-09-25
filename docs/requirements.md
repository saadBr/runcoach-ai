# Requirements

## Status

- Project: PaceCraft AI
- Document state: Approved baseline with multi-athlete onboarding extension
- Last updated: 2026-09-07
- MVP duration: Four weeks

## Actors

### Athlete

A registered user who imports their own activities, configures goals, reviews analytics, and
requests coaching recommendations. Every authenticated account maps to exactly one athlete domain
identity in the first multi-athlete release.

### System operator

The system operator who runs local services, manages environment variables, deploys the sanitized
demonstration, and reviews import or model failures.

### LLM provider

An optional external service that receives only approved structured evidence and returns a
schema-constrained coaching interpretation. The deterministic platform remains usable when
this provider is disabled.

## Functional requirements

### FR-001: Athlete profile

The system shall store an athlete profile with configurable timezone and non-sensitive display
settings for every registered account.

Acceptance:

- The profile has a stable `athlete_id`.
- Timezone-sensitive dates can be reproduced.
- Athlete-owned records are selected from the authenticated session rather than a browser-supplied
  athlete identifier.

### FR-002: Physiology configuration

The system shall store time-valid physiological settings, including observed maximum heart
rate, resting heart rate, and optional threshold values.

Acceptance:

- A setting has an effective date.
- Missing lactate-threshold information is allowed.
- Derived metrics record which configuration version they used.

### FR-003: Race goals

The athlete shall configure goals for 5K, 10K, half-marathon, or marathon events.

Acceptance:

- A goal contains distance, date, optional target time, and status.
- Readiness is evaluated relative to a selected goal and calculation date.

### FR-004: Export-file import

The system shall import actual Garmin and Strava export formats only after representative
files have been inspected.

Candidate adapters include:

- FIT activity files.
- GPX activity files.
- Known Garmin or Strava CSV export schemas.
- Garmin or Strava bulk-export archives.

Acceptance:

- Unsupported formats fail with a clear message.
- A bulk import reports total, accepted, rejected, duplicate, and warning counts.
- Direct Garmin API access is not required.

### FR-005: Validation and provenance

The system shall validate imported files before creating canonical activities.

Acceptance:

- Validation covers required fields, units, timestamp plausibility, distance, duration, and
  sensor-value ranges.
- Every source record retains provider, file hash, parser version, and import-batch identity.
- Validation findings have severity and machine-readable codes.

### FR-006: Idempotency and deduplication

The system shall prevent repeated imports from producing duplicate canonical activities.

Acceptance:

- Exact files are identified by SHA-256.
- Source activity identifiers are used when present.
- Cross-source candidates use documented time, distance, duration, and sport tolerances.
- Ambiguous matches are flagged rather than silently merged.
- Original source records continue to reference the canonical activity.

### FR-007: Activity storage

The system shall persist normalized activities, laps, trackpoints, and available sensor data.

Acceptance:

- Canonical units are documented.
- UTC timestamps and original timezone information are preserved.
- Missing heart rate, cadence, GPS, or elevation is represented explicitly.
- Garmin and Strava trackpoint streams are not naively interleaved.

### FR-008: Deterministic activity metrics

The system shall calculate versioned activity-level metrics.

The initial metrics include:

- Pace and speed.
- Elevation gain.
- Heart-rate and pace-zone time.
- Available cadence summaries.
- Data-coverage percentages.
- A documented training-load method.

Acceptance:

- Results are reproducible from stored inputs.
- Each result records algorithm version and calculation time.
- Incompatible load methods are labeled separately.

### FR-009: Training trends

The system shall present weekly volume, duration, elevation, pace, heart rate, and intensity
distribution.

Acceptance:

- Weeks follow the athlete's configured timezone.
- Missing sensor coverage is visible.
- Date-range selection does not change historical calculations.

### FR-010: Load, fitness, fatigue, and form

The system shall calculate acute and chronic workload series and modeled fitness, fatigue,
and form indicators.

Acceptance:

- Window or decay parameters are documented and versioned.
- The interface labels these values as modeled indicators.
- Acute/chronic values are not converted into medical injury probabilities.

### FR-011: Personal-best progression

The system shall identify verified personal bests for standard distances when the underlying
data is adequate.

Acceptance:

- Results distinguish whole-activity performances from derived rolling-distance efforts.
- Suspicious GPS or paused-time cases can be excluded.
- Superseded records remain historically auditable.

### FR-012: Race-readiness evaluation

The system shall evaluate readiness for 5K, 10K, half-marathon, and marathon goals using a
transparent deterministic rubric.

Acceptance:

- The output includes component values, evidence, confidence, and limitations.
- No readiness score is presented as a calibrated success probability.
- Insufficient history produces a reduced-confidence or insufficient-data result.

### FR-013: Race-time baseline and ML experiment

The system shall provide a deterministic Riegel prediction and evaluate one machine-learning
problem after the available performance labels have been audited.

Acceptance:

- Features use only information available before the predicted performance.
- Evaluation uses chronological splits.
- The experiment compares against Riegel and recent-performance baselines.
- The deployed coaching workflow uses ML only when eligibility criteria are met.
- Insufficient samples or negative results are reported honestly.

### FR-014: Controlled coaching workflow

The system shall orchestrate data-quality, training-load, performance-prediction, coaching,
and safety-review responsibilities through a controlled graph.

Acceptance:

- Deterministic agents call approved analytical services.
- LLM output follows a validated schema.
- Recommendations reference evidence identifiers.
- The safety reviewer can approve, request one revision, or return a deterministic fallback.
- The workflow functions in a provider-disabled test mode.

### FR-015: Explanations and warnings

The system shall explain why each recommendation was produced.

Acceptance:

- Explanations identify supporting metrics and their calculation dates.
- Missing or conflicting evidence is disclosed.
- Warning language is non-medical.
- Pain or symptom reports instruct the athlete to seek appropriate professional guidance.

### FR-016: Dashboard

The Streamlit MVP shall provide pages for:

- Athlete and goal configuration.
- Imports and data-quality findings.
- Training overview.
- Personal-best progression.
- Race readiness and prediction.
- Coaching recommendations.
- Experiment and model limitations.

Acceptance:

- The UI obtains persisted data through defined application/API interfaces.
- It does not duplicate deterministic analytical formulas.

### FR-017: Authenticated Strava onboarding

Every new athlete shall complete authenticated onboarding with a Strava history archive before
receiving predictions, coaching, or a generated plan.

Acceptance:

- Signup requires name, email, password, timezone, race goal, and one Strava export ZIP.
- Account creation and archive processing use resumable states rather than one long database
  transaction.
- Invalid, unsafe, or empty archives leave the account pending with a sanitized retryable result.
- `ready` requires a completed Strava import, a persisted goal, calculated analytics, and a
  generated training plan.
- Login sessions are revocable and only opaque token hashes are stored.
- Cross-athlete model research requires a separate versioned opt-in that can be withdrawn.
- Withdrawing research consent does not delete the athlete's account or disable coaching.

## Non-functional requirements

### NFR-001: Privacy

- Raw personal exports and credentials must never be committed.
- The cloud demonstration must use sanitized or synthetic data.
- Raw GPS tracks must not be sent to an LLM by default.
- Secrets must be supplied through environment variables.
- Requests must derive athlete ownership from an authenticated session and reject cross-athlete
  access.
- Passwords, bearer tokens, and raw Strava archives must never appear in application logs.
- Model-research exports must exclude athletes whose latest consent decision is not `granted`.

### NFR-002: Reproducibility

- Python is pinned to 3.12.10 for the initial implementation.
- Dependencies are locked with `uv.lock`.
- Database changes use Alembic.
- Metric and feature definitions are versioned.
- Experiments record dataset manifests, parameters, metrics, and conclusions.

### NFR-003: Reliability

- Import operations are idempotent.
- Database writes use transactions.
- A malformed file must not invalidate an entire bulk import.
- Failed jobs retain actionable error information.

### NFR-004: Testability

- Deterministic domain calculations are isolated from the UI and external LLM.
- External providers can be replaced with fakes.
- PostgreSQL integration behavior is tested against PostgreSQL.
- Statement coverage remains at least 80 percent unless a documented exception is approved.

### NFR-005: Maintainability

- Modules have explicit responsibilities and typed interfaces.
- Formatting, linting, and strict type checking run in CI.
- Architectural decisions and known limitations are documented with the implementation.

### NFR-006: Portability

- Local execution uses Docker Compose.
- Application configuration uses environment variables.
- The application image runs as a non-root user.
- The same image is suitable for a managed cloud container platform.

### NFR-007: Performance

At personal-athlete scale:

- A normal activity import should complete without distributed processing.
- Bulk imports may use an asynchronous database-backed job.
- Dashboard queries should use indexed summaries rather than repeatedly parsing raw files.
- Trackpoint processing should be batched to avoid excessive database round trips.

No high-volume or low-latency Big Data performance claim is required.

### NFR-008: Auditability

- Import, metric, model, prediction, and coaching runs have stable identifiers.
- Important outputs record input references and implementation versions.
- Agent-step decisions and safety-review results are persisted.

## Constraints

- The baseline release must remain deployable, reproducible, maintainable, and supported by validated evidence.
- The existing local single-athlete mode remains supported while authenticated multi-athlete
  onboarding is introduced incrementally.
- Exact export adapters cannot be finalized until real files are safely inspected.
- Garmin API access is not an MVP dependency.
- Historical Strava records may have less sensor data than recent Garmin records.
- The final ML target remains subject to a documented dataset and label audit.
- The initial cloud deployment must minimize operating cost and contain no raw personal activity data.
- Infrastructure and AI components must be adopted through evidence-backed architecture decisions tied to measured requirements.

## Priority

### Must have

FR-001 through FR-017, with the ML feature allowed to remain explicitly experimental if it
does not pass its evidence gate.

### Should have

- Route visualization from sanitized coordinates.
- Manual review of ambiguous duplicate candidates.
- Basic export of calculated summaries.

### Could have

- Strava OAuth.
- Course-aware prediction.
- Advanced model explanations.
- PDF report generation.

### Deferred capabilities

- Direct Garmin API integration.
- Real-time run coaching.
- Distributed event-streaming infrastructure and independently deployed domain services.
- Custom web and mobile clients.

### Explicit non-goals

- Medical diagnosis, clinical injury prediction, or treatment advice.
- Guaranteed race outcomes or claims that modeled indicators are direct physiological measurements.
