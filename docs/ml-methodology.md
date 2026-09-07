# Machine-Learning Methodology

## Status

- Project: RunCoach AI
- Document state: Provisional methodology pending label audit
- Last updated: 2026-09-05
- Deterministic evidence: exact-distance rolling interpolation
- Comparison baseline: Riegel race-time formula
- Final ML target: Not yet fixed

## Scientific position

The project must demonstrate a defensible machine-learning process, not merely train a model.

The available personal dataset currently includes approximately 11 recent challenge races
plus earlier races, time trials, and maximum-effort workouts. A race-only dataset is probably
too small for a reliable personalized predictor. The final target will therefore be selected
only after the data and labels are audited.

The project will not:

- Invent sample size or statistical power.
- Treat multiple segments from one activity as independent observations.
- Use random train/test splits for time-dependent observations.
- Use post-event information in a pre-event prediction.
- Claim population-level validity from one athlete.
- Deploy a model merely because it can be trained.
- Hide a result that fails to improve a deterministic baseline.

A negative experiment remains academically useful when its design and limitations are clear.

## Current case-study references

The following verified performances are initial reference values, not a training dataset:

| Distance | Verified time | Seconds |
|---|---:|---:|
| 5K | 18:48 | 1128 |
| 10K | 41:04 | 2464 |
| Half marathon | 1:33:26 | 5606 |
| Marathon | 3:41:06 | 13266 |

Primary evaluation context:

- Half marathon on 2026-10-25 with an initial sub-1:30 goal.
- Marathon on 2027-01-31.

The system must store these values through athlete/profile workflows rather than hard-coding
them into analytical functions.

## Phase 0: Label and data audit

The label audit occurs after safe export inspection and before fixing the final ML problem.

### Audit questions

- How many unique races exist?
- How many verified time trials and maximum-effort workouts exist?
- Which standard distances are represented?
- Which activities have accurate elapsed and moving time?
- Which activities have reliable GPS-derived rolling-distance efforts?
- Which records have heart rate, cadence, elevation, or pause information?
- Are race/workout labels present, inferable, or manually verifiable?
- Are there duplicate Garmin and Strava copies of the same performance?
- How much history exists before each candidate target event?
- Are training windows sufficiently separated to support temporal evaluation?

### Label classes

Candidate performance labels are assigned one of:

- `verified_race`
- `verified_time_trial`
- `verified_max_effort`
- `candidate_best_effort`
- `training_only`
- `excluded`

Only verified categories may enter the initial supervised target. Candidate labels require
manual review. Training-only and excluded activities may contribute prior-history features
but not performance targets.

### Audit output

The audit produces a versioned manifest containing:

- Unique activity identifier.
- Date and target distance.
- Label class and verification source.
- Timing method.
- Sensor coverage.
- Exclusion reason where applicable.
- Duplicate group.
- Eligible lookback duration.
- Dataset and label-version hashes.

The audit conclusion must recommend one of:

1. Proceed with the provisional race-time residual problem.
2. Narrow the supported target distances.
3. Define a different supervised target supported by observed labels.
4. Run the race model as an explicitly exploratory experiment only.
5. Collect additional prospective labels.

Changing the final target requires updating this document and the experiment log.

## Provisional ML problem

### Task

Predict elapsed time for a verified 5K, 10K, half-marathon, or marathon performance using
only information available before the event.

### Unit of observation

One row represents one unique verified performance activity.

If multiple standard-distance segments are derived from one activity, they share an
`activity_group_id` and must remain in the same validation split. They are not treated as
independent races.

Verified provider best efforts may enter the dataset even when the enclosing activity is
not itself near a standard distance. The target is the verified segment time, while all
training features still stop before the enclosing activity begins.

### Target

The human-readable target is:

`actual_elapsed_time_seconds`

The preferred modeled target is the log residual relative to the deterministic Riegel
prediction:

```text
target_residual =
    log(actual_elapsed_time_seconds)
    - log(riegel_predicted_time_seconds)
```

The final prediction is reconstructed as:

```text
predicted_time_seconds =
    exp(log(riegel_predicted_time_seconds) + predicted_residual)
```

This formulation asks whether recent personalized training evidence corrects a classical
baseline rather than asking a small model to rediscover the distance-time relationship.

## Deterministic baselines

### Baseline A: Riegel

For a known performance at distance `D1` and target distance `D2`:

```text
T2 = T1 * (D2 / D1) ^ k
```

The initial exponent is `k = 1.06`. Any personalized exponent must be fitted only from prior
eligible performances and reported separately.

The source performance selection rule must be versioned. It may prefer a recent verified
performance over an older lifetime best when the prediction purpose is current readiness.

### Baseline B: Recent same-distance performance

Use the most recent verified performance at the same target distance when available.

### Baseline C: Historical central estimate

Use a leakage-safe median or recency-weighted estimate from prior same-distance performances
when enough observations exist.

ML must be compared with all applicable baselines.

### Experimental training-context checkpoint

`training_context_fitness_v3` is exposed separately from the candidate supervised model. It
uses the newest verified effort, the context of its containing session, the athlete's own PB
curve, and changes in target-specific training support. It reports flat-course potential and
race readiness separately, with preparation scores, ranges, confidence, and 28-, 84-, 168-,
and 365-day evidence. This produces useful current-fitness output before the label set is large
enough for a defensible supervised model, but it remains an experimental baseline and must be
evaluated chronologically against the baselines above.

`performance_validation_v1` implements the prerequisite walk-forward baseline evaluation from
a frozen private label-audit export. For every target it excludes observations at the same or a
later timestamp, records the exact source observations, and reports aggregate and per-distance
MAE, median absolute error, MAPE, and signed error. Detailed predictions remain under ignored
private storage; only non-identifying aggregate evidence may be reported publicly.

The local label-review interface processes one candidate at a time and permits only four explicit
outcomes: verified race, verified time trial, verified maximum effort, or excluded. A verified
outcome requires a positive reviewed time; all other outcomes prohibit a target label. Updates
replace the ignored CSV atomically and rerun chronological validation immediately. Dataset
regeneration preserves prior manual decisions by activity identity. Across the HTTP boundary the
private identity and title are replaced by an opaque dataset-scoped review token and a derived
session class. These review endpoints are disabled in the production environment.

## Candidate features

Every feature has an `as_of_time` strictly earlier than the target event start.

### Event context known before the start

- Target distance.
- Log target distance.
- Goal type.
- Planned course elevation, only if entered before the event.
- Days until or since the configured goal date where relevant.

### Performance history

- Riegel prediction from prior verified performance.
- Age in days of the source performance.
- Most recent same-distance performance.
- Best verified performance in trailing 90, 180, and 365 days.
- Number of eligible prior performances.
- Prior personalized Riegel exponent, only when estimable without future data.

### Training history

For trailing 7-, 28-, 42-, 84-, 180-, and 365-day windows:

- Running distance.
- Moving duration.
- Activity count.
- Longest run distance and duration.
- Number of rest days.
- Intensity minutes by configured zone.
- Primary training load.
- Load-method coverage percentage.
- Acute load.
- Chronic load.
- Modeled form.
- Training consistency.
- Explainable counts of easy, long, progressive, tempo, hill, interval, and race sessions.
- Classified and unclassified title counts so missing labels are not treated as easy runs.

### Data-quality features

- Heart-rate coverage.
- GPS coverage.
- Percentage of training load using the selected primary method.
- Missing-value indicators.
- Number and severity of unresolved quality findings.

### Athlete context

- Time-valid observed maximum heart rate.
- Time-valid resting heart rate.
- Threshold values only when actually available.
- Days since the current physiology profile became effective.

Values that do not change within the single-athlete dataset provide no predictive variation
and may be excluded from fitting while still being recorded in the manifest.

## Forbidden leakage

The following target-event values must not be features for a prediction made before that
event:

- Actual finish time.
- Target-event pace or speed.
- Target-event average or maximum heart rate.
- Target-event cadence.
- Target-event elevation when it was not known beforehand.
- Post-event training effect or recovery values.
- A personal best created by the target event.
- Workload or readiness recalculated using the target event.
- Any manual label created from seeing the target outcome.

Feature-generation tests must verify time cutoffs.

## Preprocessing

The first scikit-learn pipeline should remain simple:

- Explicit numerical and categorical feature lists.
- Median imputation learned from the training fold only.
- Missing-value indicators for meaningful absence.
- Standardization for linear regularized models.
- One-hot encoding for small categorical fields.
- All transformations contained in a fitted pipeline.
- No preprocessing fitted on validation or test data.

Feature selection based on outcome correlation must occur inside the temporal training fold or
be avoided.

## Candidate models

### Primary candidate: Ridge regression

Reasons:

- Appropriate as a low-variance residual correction.
- Stable with correlated workload windows.
- Interpretable coefficients after standardization.
- More defensible than a complex model on a small dataset.

### Secondary candidate: Elastic Net

Use only if sparse feature selection has a documented purpose and hyperparameter tuning can
be performed without exhausting the temporal validation data.

### Non-linear candidate

A tree ensemble or gradient-boosting model may be compared only if the label audit finds
enough unique activities. It must not become the default merely because training error is
lower.

### Excluded initial models

- Deep neural networks.
- Large language models as predictors.
- Unvalidated injury classifiers.
- Models trained on synthetically invented race outcomes.
- Complex ensembles without an adequate validation set.

## Temporal evaluation

### Ordering

Sort unique performance activities by start time.

### Split strategy

Preferred strategy:

1. Reserve the latest eligible events as an untouched chronological test set.
2. Use expanding-window validation on earlier events.
3. Keep all rows from one activity in one fold.
4. Fit preprocessing and model parameters separately inside each training fold.
5. Preserve a gap or purge overlapping feature windows when necessary.

If too few events exist for an untouched test set, the model remains exploratory and the
limitation is explicit.

### Why random cross-validation is rejected

Random splits allow later fitness state and overlapping historical windows to inform earlier
predictions. This produces optimistic performance estimates that do not represent the
intended real-world use.

## Metrics

Report:

- Mean absolute error in seconds.
- Mean absolute error in minutes.
- Median absolute error.
- Root mean squared error.
- Mean absolute percentage error.
- Signed mean error to detect optimistic or pessimistic bias.
- Error by target distance when sample size permits.
- Number of unique activities in every split.
- Baseline-relative error difference.

Percentage metrics are secondary because all targets are positive but span substantially
different durations.

## Uncertainty

The output is a point estimate plus an empirically derived uncertainty interval when the
validation sample supports it.

The interface must distinguish:

- Model residual uncertainty.
- Missing-data confidence.
- Distance extrapolation.
- Lack of recent verified performance.
- Insufficient sample size.

An interval from a small validation set is descriptive, not a guaranteed statistical coverage
interval.

## Eligibility gates

The provisional engineering gate is:

- At least 30 unique verified performance activities overall.
- At least 8 later unique activities available for chronological evaluation.
- More than one target distance represented.
- No unresolved leakage failure.
- Complete provenance for target and feature rows.

These thresholds are not a claim of statistical power. They determine whether fitting the
provisional model is operationally worthwhile.

### Coaching eligibility

A trained model may influence coaching only when:

- It passes all data and leakage checks.
- It improves chronological MAE over the applicable Riegel baseline.
- Its error is not materially worse for the active target distance.
- The prediction is within the model's observed feature and distance support.
- The model artifact and feature version are available.
- The prediction carries limitations and confidence.

Otherwise, the coaching workflow uses the deterministic baseline and reports why ML was not
eligible.

## Experiment tracking

Each experiment records:

- Experiment identifier and date.
- Code commit.
- Dataset-manifest hash.
- Label version.
- Feature version.
- Target definition.
- Inclusion and exclusion counts.
- Temporal split dates and activity groups.
- Preprocessing pipeline.
- Model and hyperparameters.
- Random seed where applicable.
- Library versions.
- Baseline and model metrics.
- Per-distance errors.
- Artifact checksum.
- Eligibility decision.
- Conclusion and next action.

The human-readable record lives in `docs/experiment-log.md`; structured metadata is later
stored in PostgreSQL.

## Reproducibility

- Dependencies are locked with `uv.lock`.
- Model training uses a fixed seed where the algorithm is stochastic.
- Feature calculations are deterministic and versioned.
- Dataset rows are identified by canonical IDs and a manifest hash.
- Private data is never committed.
- Tests use synthetic or sanitized fixtures.
- Serialized artifacts are checksum-verified and kept outside Git.

## Model monitoring for the MVP

The single-athlete MVP does not need a production monitoring platform. It will record:

- Prediction date.
- Model and feature versions.
- Predicted time and interval.
- Actual result when later verified.
- Absolute and signed error.
- Whether features were outside observed ranges.
- Whether the prediction influenced coaching.

Accumulated prediction outcomes become material for the report and future retraining.

## Alternative ML target

If the label audit rejects the provisional race-time problem, a replacement must satisfy all
of these conditions:

- It has an observable target rather than a circular score generated by the same rules used as
  features.
- It has enough unique chronological examples.
- It supports a real user decision.
- It can be evaluated against a simple baseline.
- It does not claim medical diagnosis.
- It can be implemented as a reproducible pipeline with documented assumptions, tests, and evaluation.

No alternative target is approved until the audit provides evidence.

## Threats to validity

### Internal validity

- Incorrect race or effort labels.
- Duplicate source records.
- Timing errors caused by pauses or GPS.
- Leakage from overlapping historical windows.
- Changing physiology or zone configuration.

### External validity

- One athlete cannot support population-level conclusions.
- Personal history may not represent other ages, training backgrounds, climates, or courses.
- Model results may not transfer between race distances.

### Construct validity

- A race finish time includes weather, course, pacing, illness, nutrition, and motivation that
  may be absent from the features.
- Modeled training load is not direct physiological adaptation.
- Maximum observed heart rate is not a laboratory threshold measurement.

### Conclusion validity

- Small samples create unstable estimates.
- Repeated experiments can overfit the test period.
- Aggregate metrics may hide distance-specific failure.
- A small numerical improvement may not be practically meaningful.

## Initial references to verify for the report

- Riegel, P. S. (1981). Athletic Records and Human Endurance.
- Banister and Calvert's training-impulse and fitness-fatigue work.
- Methodological literature on temporal validation and data leakage.
- Sports-science criticism of causal injury claims based on acute/chronic workload ratios.

Full citations and source-quality notes will be maintained in the graduation report material.
