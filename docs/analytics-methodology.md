# Deterministic Analytics Methodology

## Purpose

This document defines the deterministic calculations used to transform canonical running
activities and sensor observations into reproducible performance and workload indicators.

These calculations are implemented in normal Python code. They do not depend on an LLM,
agent, user interface, or external coaching provider.

The language-model layer may later interpret these validated results, but it must not
recalculate or silently alter them.

## Scientific boundaries

The analytics layer produces modeled indicators rather than direct physiological
measurements.

In particular:

- Training load is an analytical proxy.
- Fitness, fatigue, and form are modeled state variables.
- Heart-rate zones depend on an observed maximum heart rate.
- Edwards TRIMP is an intensity-weighted summary, not a medical measure.
- Positive form does not guarantee race readiness.
- Negative form does not diagnose overtraining or injury.
- Missing sensor data is represented explicitly rather than imputed as normal physiology.

## Versioning

The initial deterministic calculation versions are:

| Calculation | Version |
|---|---|
| Per-activity metrics | `activity_metrics_v1` |
| Duration workload method | `duration_minutes_v1` |
| Heart-rate zone method | `max_hr_5_zone_v1` |
| Daily workload state | `daily_load_v1` |

Changing a formula, threshold, sample-handling rule, or semantic interpretation requires a
new version identifier.

Existing historical results remain stored so that calculations can be audited and compared.

## Input data

### Canonical activity inputs

Each activity calculation uses:

- Canonical distance in meters
- Moving time in milliseconds
- Elapsed time in milliseconds
- Local activity date
- Ordered sensor samples, when available
- The physiology profile valid on the local activity date

Activities marked `excluded` are not included.

### Sensor inputs

The deterministic analytics contract receives only the fields needed for calculation:

- Elapsed time
- Heart rate
- Whether position is available
- Cadence
- Paused status

Raw latitude and longitude values are not passed into the analytics calculation or its input
hash. Only a Boolean position-availability value is used for GPS coverage.

### Physiology-profile validity

A physiology profile is valid from `valid_from`, inclusive, until `valid_to`, exclusive.

An activity may use a profile only when its local date falls inside that period. A profile is
not applied retroactively to earlier activities.

The configured profile currently records:

- Observed maximum heart rate: 195 bpm
- Lowest observed resting heart rate: 45 bpm
- Lactate-threshold heart rate: unavailable
- Threshold pace: unavailable

The absence of a formally tested lactate threshold is preserved rather than estimated.

## Pace calculations

Moving pace is calculated as:

`moving pace seconds per km = moving time seconds / distance km`

Elapsed pace is calculated as:

`elapsed pace seconds per km = elapsed time seconds / distance km`

A pace is unavailable when distance or the relevant duration is zero.

Moving pace is stored in the principal pace column. Elapsed pace is retained in the
versioned additional-metrics document.

## Effective activity duration

Training duration uses moving time when moving time is greater than zero.

If moving time is unavailable or zero, elapsed time is used as the deterministic fallback.

The selected duration is called the effective duration.

## Sensor coverage

Heart-rate, GPS, and cadence coverage are measured by time rather than by counting samples.

For each ordered pair of sensor observations:

1. Calculate the interval to the following observation.
2. Ignore non-positive intervals.
3. Ignore intervals whose starting observation is marked paused.
4. Cap the credited interval at 10 seconds.
5. Credit the interval to a sensor only when the starting observation contains that sensor.

The cap prevents one isolated observation from incorrectly claiming coverage across a long
recording gap.

Coverage is calculated as:

`coverage percent = credited sensor duration / effective activity duration * 100`

Coverage is bounded between zero and 100 percent.

This calculation distinguishes activities with complete recent sensor streams from
historical activities that contain only route or summary data.

## Heart-rate zones

The initial zone model uses percentage of observed maximum heart rate.

| Zone | Percentage of observed maximum HR | Edwards weight |
|---|---:|---:|
| Zone 1 | Below 60 percent | 1 |
| Zone 2 | 60 to below 70 percent | 2 |
| Zone 3 | 70 to below 80 percent | 3 |
| Zone 4 | 80 to below 90 percent | 4 |
| Zone 5 | 90 percent or higher | 5 |

Zone duration is calculated from the same capped time intervals used for heart-rate
coverage.

Each stored zone component contains:

- Zone identifier
- Observed seconds
- Percentage of observed heart-rate time

Zone percentages use observed heart-rate time as their denominator. They do not pretend
that periods without heart-rate data belonged to a particular zone.

Heart-rate zones are unavailable when no valid observed maximum heart rate applies to the
activity date.

## Edwards TRIMP

Edwards TRIMP is calculated as:

`Edwards TRIMP = sum(zone minutes * zone weight)`

The weights are 1 through 5 for Zones 1 through 5.

This value combines duration and cardiovascular intensity. It is stored as an additional
per-activity metric when both conditions are satisfied:

- A valid observed maximum heart rate applies.
- The activity contains usable heart-rate intervals.

Edwards TRIMP is not used as the initial full-history workload series because historical
heart-rate coverage is incomplete. Doing so would make older activities appear falsely
easy or unloaded.

## Duration workload

The initial longitudinal workload method is:

`activity load = effective duration in minutes`

Daily load is the sum of activity loads on the athlete's local calendar date.

This method is intentionally simple and transparent. It provides consistent coverage across
both historical Strava activities and recent Garmin activities.

Its limitation is equally important: one minute of easy running and one minute of intense
running receive the same load.

Duration load and Edwards TRIMP therefore remain distinct methods. They must not be merged
without a documented calibration.

## Continuous daily series

The workload series contains every calendar day from the first eligible activity through the
requested as-of date.

Days without running are stored with zero daily load. Rest days are not omitted.

This prevents exponential workload state from remaining artificially unchanged across gaps.

## Acute and chronic workload

Acute and chronic states use deterministic exponential recurrences.

For each day:

`next state = previous state + (daily load - previous state) / time constant`

The time constants are:

- Acute load: 7 days
- Chronic load: 42 days

The states start at zero on the first day of the series.

### Availability gates

Acute load is unavailable until seven calendar days of history have been processed.

Chronic load, fitness, fatigue, and form are unavailable until 42 calendar days have been
processed.

These gates avoid presenting early initialization values as mature workload estimates.

## Fitness, fatigue, and form

The initial model defines:

- Fitness index as chronic load
- Fatigue index as acute load
- Form index as chronic load minus acute load

Therefore:

- Negative form indicates that recent load exceeds the longer-term load state.
- Positive form indicates that recent load has fallen below the longer-term state.
- A value near zero indicates similar acute and chronic states.

These are model interpretations only. They do not independently establish readiness,
adaptation, illness, overtraining, or injury risk.

## Daily-load coverage

The duration workload method has 100 percent method coverage when canonical activity
duration is available.

This coverage value means the selected method could be calculated. It does not mean that
heart rate, GPS, cadence, or every physiological signal was available.

Sensor coverage remains stored separately in per-activity metrics.

## Input hashing

Each per-activity metric stores a SHA-256 hash of the exact calculation inputs:

- Algorithm version
- Activity identifier
- Distance
- Moving and elapsed duration
- Applicable physiology-profile identifier
- Applicable observed maximum heart rate
- Ordered privacy-preserving sensor values

Raw coordinates are excluded.

The unique identity is:

`activity_id + algorithm_version + input_hash`

When inputs do not change, recalculation reuses the existing metric. When an input changes,
a new versioned metric row is created without deleting the earlier result.

## Daily-load persistence

Daily workload rows are uniquely identified by:

`athlete_id + local_date + load_method + algorithm_version`

Recalculation follows three outcomes:

- Create a row when none exists.
- Reuse a row when all calculated values are unchanged.
- Update the versioned series row when its deterministic inputs produce changed values.

The calculation is performed inside one database transaction.

## Validation against the current dataset

The first complete calculation on 2026-08-27 produced:

| Measure | Result |
|---|---:|
| Canonical running activities processed | 130 |
| Activity metrics created | 130 |
| Activities inside the configured profile period | 90 |
| Activities with Edwards TRIMP | 85 |
| Daily workload rows | 829 |
| Average heart-rate coverage across all activities | 65.08 percent |
| Average GPS coverage across all activities | 96.86 percent |
| Average cadence coverage across all activities | 65.08 percent |

The sensor-coverage pattern is consistent with the known source history:

- Recent Garmin-era activities provide complete heart-rate and cadence streams.
- Historical Strava activities generally lack those sensors.
- Route-position coverage exists across most of the full history.

A second identical calculation created zero metrics, updated zero daily rows, reused all 130
activity metrics, and reused all 829 daily rows.

This verifies deterministic idempotency for the current calculation versions and persisted
dataset.

## Example workload interpretation

On 2026-08-23, the duration model reported:

- Daily load: 141.39 minutes
- Acute load: 71.46
- Chronic load: 49.34
- Form: -22.12

After four zero-load days, the 2026-08-27 state was:

- Acute load: 38.57
- Chronic load: 44.81
- Form: +6.24

This demonstrates the expected behavior of the exponential model: acute load falls faster
than chronic load during rest.

It does not by itself justify a recommendation to train, race, or rest. Later readiness and
coaching logic must combine workload with goal context, performance evidence, data quality,
and explicit safety rules.

## Testing strategy

The analytics implementation includes tests for:

- Moving and elapsed pace
- Duration workload
- Heart-rate coverage
- GPS and cadence coverage
- Heart-rate zones
- Edwards TRIMP
- Sample-gap capping
- Paused intervals
- Rest-day insertion
- Acute and chronic recurrence
- Availability gates
- Profile validity periods
- Versioned activity-metric persistence
- Daily-load persistence
- Input-change recalculation
- Excluded activities
- Transaction rollback
- CLI orchestration
- Idempotent recalculation

Golden deterministic tests use explicit expected numeric values rather than copying the
production implementation.

## Current limitations

- Duration load does not represent intensity.
- Edwards TRIMP cannot provide a consistent full-history series because historical HR is
  missing.
- Maximum-HR zones are less individualized than tested threshold-based zones.
- The observed maximum heart rate may change with future evidence.
- Resting heart rate is stored but is not yet used in the initial calculations.
- Fitness and fatigue state variables have not been validated against independent
  physiological measurements.
- The model does not currently incorporate sleep, HRV, subjective soreness, illness,
  temperature, course difficulty, or strength-training load.
- The model does not produce medical diagnoses.
- Results are validated for the available single-athlete dataset and are not population
  evidence.

## Elevation normalization and weekly aggregation

Elevation gain is normalized before persistence because provider exports use different units:

- Strava activity-summary elevation gain and loss are expressed in metres.
- Garmin summarized-activity elevation gain and loss are expressed in centimetres and are divided by 100.
- A calibration audit across 82 matched non-zero activities produced a median raw Garmin-to-Strava ratio of approximately 100.98, supporting this conversion.

After normalization, 129 of 130 canonical running activities contain an elevation-gain value. The remaining activity is a historical summary-only record without elevation evidence.

Weekly elevation is the sum of canonical activity-level elevation gain for runs within each calendar week. A week containing no runs returns `null` rather than manufacturing a measured zero. This distinguishes absence of contributing activities from an activity whose recorded elevation gain is genuinely zero.

The current implementation uses provider activity-summary elevation rather than recalculating ascent from GPS altitude samples. Provider elevation correction, device barometer behavior, GPS noise, and platform-specific smoothing may therefore produce small differences between sources. Canonical source selection and field provenance must remain available when interpreting these totals.

## Verified performance presentation

Current personal bests are stored as verified progression events rather than inferred from
activity names. Each record identifies its canonical activity, standard distance, elapsed
time, effort type, verification status, verification source, and algorithm version.
Superseded records remain stored for historical audit while the analytical view returns only
the current record for each supported distance.

### Exact-distance trackpoint evidence

Longer workouts may contain a valid standard-distance effort between a warm-up and cool-down.
For these activities, `rolling_distance_interpolation_v1` searches the cumulative-distance
trace for the fastest exact 5K, 10K, half-marathon, or marathon interval. Segment start and
finish times are linearly interpolated at all piecewise-linear breakpoints, and the minimum
positive elapsed interval is selected deterministically. Distance samples must be ordered by
elapsed time and cumulative distance must not decrease.

This derived interval is evidence, not an automatic label. A provider best effort or manual
review supplies the verified result stored in `personal_bests`; small differences caused by
sampling and provider rounding are preserved rather than silently rewritten.

The deterministic Riegel calculation remains an internal comparison benchmark:

```text
T2 = T1 * (D2 / D1) ^ 1.06
```

Its output is retained in unit tests for comparison with chronological machine-learning
experiments. It is not persisted, exposed by the performance API, or presented in the
dashboard as a race prediction because it does not use training volume, current workload,
course, weather, fatigue, or race execution.

## Performance label and feature audit

The private performance dataset nominates whole activities within the configured distance
tolerance of 5K, 10K, half-marathon, and marathon. It also includes verified provider best
efforts linked to longer activities, such as a rolling 5K inside a workout. A candidate does
not become a training label merely because its distance matches. Existing verified
personal-best evidence prefills reviewed rows; every other candidate remains `unreviewed`
with an empty verified target until human review classifies it.

The feature bundle is versioned as `performance_training_features_v3`. For each candidate it
calculates 7-, 28-, 42-, 84-, 180-, and 365-day pre-event aggregates: run count, distance,
moving time, longest run, weighted pace, elevation gain, heart-rate availability, duration
load, and title-derived session counts. Session rules are separately versioned as
`title_rules_v1`; unrecognized titles remain explicitly unclassified. The dataset also
records the prior day's acute, chronic, and form state and any verified PBs achieved before
the event.

The leakage boundary is strict: activity features use only activities whose start precedes
the candidate start, workload state ends on the previous local date, and prior-PB features
exclude the candidate and all later performances. Unreviewed rows have no verified elapsed
time and must not enter model fitting or evaluation.

The CSV contains private activity names and identifiers and may only be written below
`RUNCOACH_PRIVATE_DATA_DIR`. It is a review artifact and must not be committed.

## Experimental current-fitness estimate

The dashboard may expose `training_context_fitness_v2` as an experimental capability and
readiness estimate while the supervised training model remains under chronological
evaluation. It is not the Riegel formula and is not presented as a validated race guarantee.

The calculation:

1. Selects the newest active verified PB as the current fitness anchor.
2. Finds the athlete's best older verified mark at that same distance when available.
3. Classifies the anchor activity title. When a best-effort segment is embedded inside a
   substantially longer quality session, applies a bounded four-percent workout-reserve
   factor. A standalone verified maximum effort receives a smaller bounded reserve; a
   verified whole-activity race receives none.
4. Calculates the resulting same-distance capacity improvement factor and applies it to the
   athlete's active PB at each other distance, preserving the athlete's demonstrated
   endurance relationship rather than imposing a population exponent.
5. For each target independently, compares current 84-day volume and longest-run evidence
   with the training immediately preceding that target's PB. The adjustment is bounded and
   more sensitive for longer distances.
6. Reports flat-course fitness potential separately from race readiness. Readiness uses a
   zero-to-one preparation score built from recent frequency, volume, and longest-run support.
7. Reports a distance-specific readiness range and confidence. The 28-, 84-, 168-, and
   365-day histories are returned so recent training is not interpreted in isolation.

Neither output can be slower than the active verified PB. Fitness potential assumes favorable
conditions and a full effort; readiness can be slower than potential when preparation for the
target distance is incomplete.

This estimator is useful as an immediately visible, auditable checkpoint. It does not satisfy
the release gate for the future supervised training-feature model. Chronological evaluation,
course and weather context, taper state, illness, sleep, and race execution remain absent.
OpenAI may explain the stored evidence and limitations but does not calculate the numeric
times or invent measurements.

## Goal-based training-plan preview

`goal_plan_preview_v1` turns one selected race distance, race date, optional target time, and
weekly running frequency into a read-only plan preview. It consumes the versioned
`training_context_fitness_v2` result rather than recalculating performance independently.

The method:

1. Requires between two and 52 weeks before race day.
2. Classifies the requested target as fitness-based, achievable, challenging, or aggressive
   relative to current potential, readiness, and available preparation time.
3. Uses trailing 28-day volume as the starting load, reduced when the selected running-day
   count is lower than recent frequency.
4. Starts the first week below that adjusted baseline, limits normal build steps to 3.5
   percent, inserts a cutback every fourth week, and tapers before race week.
5. Selects target-specific quality and long-run emphasis. Marathon long runs progress from
   32 percent of weekly volume in the base phase to 35 percent in build and 38 percent in the
   specific phase, with a 35 km ceiling. Other distances retain their target-specific shares
   and ceilings. Easy and recovery volume absorbs the remaining weekly load.
6. Derives transparent pace ranges from current 5K capacity and target-distance readiness.

The selected goal and generated preview can now be stored as an immutable active plan version.
Refreshing with identical evidence is idempotent; changed training evidence creates a new
version and supersedes the prior snapshot without deleting it. The plan does not yet observe
completed sessions, reschedule missed work, or react to pain, illness, sleep, weather, or
unexpected fatigue. Those require adherence evidence and a controlled coaching workflow. The
generated guardrails prohibit compensating for missed hard sessions and state
that the output is not medical advice.
