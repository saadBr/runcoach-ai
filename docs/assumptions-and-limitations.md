# Assumptions and Limitations

## Status

- Document type: Living assurance and scope record
- Initial version: 2026-08-23
- Review rule: Update whenever data, algorithms, deployment, or intended use changes

## Purpose

PaceCraft AI combines personal activity records, deterministic training analytics, statistical
models, and controlled language-model interpretation. Each layer depends on assumptions and has
limits that affect how its outputs may be interpreted.

This document distinguishes:

- An assumption: a condition treated as true until it is verified or rejected.
- A limitation: a known boundary that constrains validity, generalization, or operation.
- A warning indicator: a non-medical signal that may justify caution or human review.

Recording these boundaries is part of system correctness. It is not a substitute for resolving
defects or collecting better evidence.

## Intended use

The system supports one runner in reviewing training history, workload patterns, performance
progression, race readiness, and evidence-backed coaching recommendations.

It is intended for:

- Retrospective activity analysis.
- Training-load and trend exploration.
- Race-planning support.
- Transparent comparison of deterministic and learned predictions.
- Reproducible experimentation on personal longitudinal data.

It is not a medical device and does not provide diagnosis, treatment, emergency guidance, or a
guarantee of performance.

## Known athlete context

The current case-study context is:

| Item | Current information | Verification status |
| --- | --- | --- |
| Athlete count | One athlete, with `athlete_id` retained | Confirmed design decision |
| Historical source | Strava contains the longer history | Export not yet inspected |
| Recent rich source | Garmin data begins in April 2026 | Export not yet inspected |
| 5K reference | 19:41 | Athlete-verified reference |
| 10K reference | 41:30 | Athlete-verified reference |
| Half-marathon reference | 1:32:00 | Athlete-verified reference |
| Marathon reference | 3:42:00 | Athlete-verified reference |
| Observed maximum heart rate | Approximately 195 bpm | Observed, not laboratory tested |
| Lowest observed resting heart rate | Approximately 45 bpm | Observed minimum, not a stable baseline |
| Lactate-threshold heart rate | Not formally tested | Unknown |
| Primary goal | Casablanca Half Marathon, 2026-10-25, initially sub-1:30 | Athlete-defined goal |
| Following major goal | Marrakech Marathon, 2027-01-31 | Athlete-defined goal |

Reference performances are starting evidence. They do not automatically become training labels
until source records, distances, dates, courses, and effort classifications are audited.

## Assumption register

| ID | Assumption | Why needed | Validation method | Status |
| --- | --- | --- | --- | --- |
| A-001 | Exported files contain stable timestamps and activity identifiers when available | Ordering and deduplication | Inspect representative exports | Open |
| A-002 | Distances and elapsed times use recoverable units | Canonical normalization | Parser contract tests and source documentation | Open |
| A-003 | The athlete can manually resolve ambiguous races and duplicates | Label quality | Review workflow | Open |
| A-004 | Older Strava data has less sensor coverage than recent Garmin data | Missing-data strategy | Coverage report after import | Open |
| A-005 | Garmin records from April 2026 provide richer HR, cadence, GPS, or lap data | Recent feature design | Schema and missingness audit | Open |
| A-006 | Activity timestamps can be converted to a consistent timezone policy | Chronological analytics | Compare source metadata and known events | Open |
| A-007 | Verified performance events can be ordered without using future information | Temporal evaluation | Label audit | Open |
| A-008 | Heart-rate observations are physiologically plausible after validation | Intensity analytics | Range, continuity, and device checks | Open |
| A-009 | A deterministic load method can be applied consistently to activities with its required inputs | Trend calculation | Method-coverage report | Open |
| A-010 | Sanitized demonstration data preserves analytical behavior without retaining identity | Cloud evaluation | Automated and manual privacy review | Open |
| A-011 | Structured evidence is sufficient for the initial coaching workflow | Recommendation grounding | Agent evaluation and failure analysis | Open |
| A-012 | Cloud services can run the container and PostgreSQL topology within the approved budget | Deployment | Platform verification and smoke test | Open |

An open assumption must not be presented as an observed fact. When evidence resolves an assumption,
update its status and link the relevant import batch, test, experiment, or decision record.

## Data limitations

### Export variability

Garmin and Strava exports may differ by export type, device, account settings, activity age, and
platform schema version. FIT, GPX, TCX, and CSV formats do not necessarily contain the same fields
or sampling resolution.

Consequences:

- Parsers require adapter-specific validation.
- Feature availability varies by activity and period.
- Aggregate values from one platform may not exactly match values recomputed from trackpoints.
- Unknown extensions must be retained as provenance or reported, not silently reinterpreted.

### Historical sensor coverage

Older Strava activities may contain only summary distance, time, and elevation. Recent Garmin
activities may include heart rate, cadence, laps, GPS, temperature, power, and denser samples.

Consequences:

- Missing values are not automatically zero.
- Features with low historical coverage may bias a model toward recent periods.
- Comparisons across periods must disclose method and sensor coverage.
- The system needs missingness indicators and coverage-aware analytics.

### Device and algorithm differences

Garmin, Strava, and the project may calculate moving time, elevation gain, pace, calories, and
training metrics differently. Device firmware and platform algorithms may change without a
retroactive explanation.

The canonical model must preserve source values separately from project-derived values and record
the method version used for each calculation.

### GPS limitations

GPS data may contain drift, tunnels, urban-canyon errors, pauses, duplicated points, implausible
speeds, and privacy-sensitive locations.

GPS-derived pace or distance must be accompanied by quality checks. Raw coordinates are private and
are not required for the public demonstration.

### Deduplication uncertainty

The same activity may appear in Garmin and Strava with shifted timestamps, different distances,
different names, or partial sensor streams. Exact identifiers solve only some cases.

The deduplication process may produce:

- Confirmed duplicates.
- Confirmed distinct activities.
- Ambiguous candidates requiring manual review.

Automatic deletion of an ambiguous record would risk irreversible loss. The system therefore keeps
source provenance and records the deduplication decision.

## Physiological and training-metric limitations

### Heart-rate zones

The observed maximum heart rate of approximately 195 bpm is not a laboratory measurement. The
lowest observed resting heart rate of approximately 45 bpm is not necessarily the current resting
baseline. Lactate-threshold heart rate is unknown.

Consequences:

- Zone boundaries are estimates.
- Threshold-based zones must not be claimed until a defensible threshold is available.
- Changes to profile values require recalculation and method-version tracking.
- Sensor spikes and wrist-based measurement error can distort intensity summaries.

### Acute and chronic workload

Acute load, chronic load, fitness, fatigue, and form are modeled indicators derived from selected
inputs and time constants. They are not direct measurements of biological adaptation.

Their interpretation depends on:

- The selected load method.
- Completeness of activity history.
- Heart-rate or intensity coverage.
- Decay constants and initialization.
- Inclusion of non-running training.
- The athlete's current health and life stress, which may be absent from the data.

### Injury-risk language

Rapid workload change, monotony, declining performance, unusual heart-rate response, and repeated
hard sessions may justify warning indicators. They do not establish injury probability or medical
causation for this athlete.

The system must use language such as `warning indicator`, `unusual pattern`, or `review suggested`.
It must not diagnose injury or advise treatment.

### Race readiness

Readiness is a model combining recent training, workload, performance evidence, recovery signals,
goal demands, and data quality. It is not a single physiological truth.

Weather, course profile, travel, illness, sleep, nutrition, pacing, and race-day conditions may be
unknown. Readiness outputs must show component evidence, uncertainty, and missing information.

## Machine-learning limitations

### Label volume

The verified race-only sample may be small. The recalled event count includes approximately 11
challenge races plus earlier races, time trials, and maximum-effort workouts, but the usable count
is unknown before import and label audit.

A small dataset limits:

- Holdout size.
- Hyperparameter selection.
- Model complexity.
- Distance-specific evaluation.
- Confidence in generalization.
- Statistical comparison between models.

The project will not invent significance or reliability. If eligibility gates fail, deterministic
baselines remain the valid result.

### Single-athlete generalization

A model fitted to one athlete estimates patterns within that athlete's recorded history. It does
not establish accuracy for other runners, demographic groups, training systems, or performance
levels.

Retaining `athlete_id` makes the data model extensible but does not make the evidence multi-athlete.

### Temporal dependence and drift

Activities and performances are correlated through time. Random train-test splits can leak later
fitness states into earlier predictions. Training response, devices, goals, and behavior may also
change over time.

Evaluation must therefore be chronological and should report where performance changes across
periods.

### Feature leakage

Post-event values, future personal bests, later training, race results, or statistics calculated
over the complete timeline can make a model appear unrealistically accurate.

Every feature must have an `available_at` interpretation. Preprocessing and personalized parameters
must be fitted within each training window.

### Prediction uncertainty

Point predictions cannot express all uncertainty. With limited observations, formal calibrated
intervals may be unreliable. The system must report the estimation method, data coverage,
applicable validation error, and known omitted factors.

## Coaching and language-model limitations

The language model interprets validated structured evidence. It does not calculate authoritative
pace, load, zones, readiness, or race predictions.

Language-model limitations include:

- Nondeterministic wording.
- Unsupported inference.
- Provider outages and latency.
- Model-version changes.
- Prompt-injection attempts in imported free text.
- Privacy exposure if excessive context is transmitted.

Controls include:

- Typed evidence and output contracts.
- Deterministic calculations outside the model.
- Evidence identifiers for recommendations.
- Numeric consistency checks.
- Safety review and fallback paths.
- Provider abstraction.
- Minimal context without raw GPS tracks.
- LLM-disabled operation.

A coherent explanation is not proof that a recommendation is effective.

## Evaluation limitations

- Coverage percentage does not establish scientific validity.
- Passing unit tests does not prove parser compatibility with unseen exports.
- Synthetic fixtures cannot reproduce every device anomaly.
- Backtesting cannot reproduce race-day decision making.
- A successful cloud smoke test does not establish high availability.
- Recommendation contract tests do not establish long-term coaching benefit.
- Performance metrics on a small holdout may be unstable.

Evaluation evidence must be interpreted at the level it actually supports.

## Privacy and security limitations

Raw activity files may contain identifying routes, home locations, timestamps, names, account
identifiers, device identifiers, and free text.

Repository ignores reduce accidental commits but do not encrypt local files or prevent every human
error. Local device security, backups, access control, and manual review remain necessary.

Sanitization reduces risk but may not guarantee anonymity when rare routes, dates, or performance
patterns can be combined with external information. The public dataset must therefore minimize
fields and undergo manual review.

The project does not claim formal certification against a privacy or security standard.

## Deployment limitations

- Managed-platform limits and behavior may change.
- A small deployment may sleep, restart, or have constrained database resources.
- The baseline topology does not provide multi-region failover.
- Platform logs require review for accidental sensitive content.
- The public environment cannot validate private raw-file ingestion when upload is disabled.
- LLM-backed demonstrations depend on provider availability if explicitly enabled.

These limits affect operations, not the reproducibility of the containerized local system.

## Scale positioning

The project applies data-engineering principles including heterogeneous ingestion, canonical
schemas, provenance, idempotency, quality validation, longitudinal feature computation, and
reproducible pipelines.

The current single-athlete dataset does not establish genuine Big Data scale. No claim is made that
the system requires distributed storage or computation. Kafka, distributed processing, and cluster
orchestration remain possible architectural evolutions when measured volume, velocity, availability,
or isolation requirements support them.

## External-validity boundaries

Results are bounded by:

- One athlete.
- The available historical period.
- The devices and platforms represented.
- The observed training methods and race distances.
- The local climate, terrain, and event context.
- The quality of manually verified labels.

Claims in the report and presentation must remain within these boundaries.

## Limitation-response policy

| Condition | Required system response |
| --- | --- |
| Missing required input | Return `insufficient data` and identify the missing input |
| Low feature coverage | Exclude the feature or expose its coverage limitation |
| Ambiguous duplicate | Preserve both source records and request review |
| Failed label audit | Do not train the proposed model |
| ML eligibility failure | Use deterministic baseline and explain why |
| Conflicting evidence | Preserve the conflict for safety review |
| Unsupported medical inference | Reject or rewrite as a non-medical warning |
| LLM failure | Return deterministic evidence or a safe template |
| Sanitization uncertainty | Do not publish the record |

## Review checklist

At each verified release, review whether:

- Open assumptions gained evidence.
- New data sources introduced schema assumptions.
- Metric definitions or parameters changed.
- Sensor coverage changed materially.
- A learned model passed or failed its gates.
- Recommendation behavior introduced new risks.
- Deployment changed privacy exposure.
- Report claims remain supported.
- Superseded limitations can be closed with evidence.

## Current conclusion

PaceCraft AI can provide a rigorous personalized case study when its outputs remain traceable to
validated data and versioned methods. Its most important boundaries are incomplete historical
sensor coverage, uncertain race-label volume, single-athlete external validity, estimated
physiological parameters, and the difference between warning indicators and medical conclusions.

These boundaries must remain visible in the product, experiments, report, and presentation.
