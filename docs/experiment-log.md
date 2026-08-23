# Experiment Log

## Status

- Document type: Living experimental record
- Initial version: 2026-08-23
- Scope: Data audits, deterministic baselines, machine-learning experiments, and coaching evaluations
- Result policy: No metric is reported until the corresponding experiment has been executed

## Purpose

This log provides a reproducible record of every analytical and machine-learning experiment
performed in RunCoach AI. It separates proposals from completed work, prevents selective
reporting, and connects each conclusion to a dataset manifest, code revision, feature definition,
evaluation protocol, and stored artifact.

The log is the authoritative index of experiments. Detailed machine-readable manifests and
artifacts may be stored outside this file, but every experiment must have an entry here.

## Integrity rules

1. Register an experiment before inspecting its final evaluation results.
2. Never replace an earlier result; append a new experiment with a new identifier.
3. Record failed, inconclusive, and negative experiments.
4. Distinguish measured results from hypotheses and planned work.
5. Use chronological evaluation for time-dependent athlete data.
6. Fit preprocessing only on the training portion of each split.
7. Compare learned models with deterministic and simple statistical baselines.
8. Record missing-data rules and excluded labels explicitly.
9. Never infer significance from a small sample without an appropriate analysis.
10. Keep private source files and identifying artifacts outside Git.

## Experiment identifiers

Identifiers use the form `EXP-NNN`, assigned sequentially.

| Status | Meaning |
| --- | --- |
| Proposed | Question and protocol are recorded but work has not started |
| Running | Data preparation or evaluation is in progress |
| Completed | Protocol was executed and results were recorded |
| Inconclusive | Execution completed but evidence cannot support a decision |
| Superseded | A later experiment replaces the protocol, not the historical result |
| Cancelled | Experiment was stopped with a documented reason |

## Required dataset manifest

Each executed experiment must reference a manifest containing:

- Dataset identifier and creation timestamp.
- Git commit containing the dataset-building code.
- Source categories included, without private filenames in Git.
- Observation count before and after every eligibility rule.
- Date range and chronological ordering rule.
- Target definition and unit.
- Feature schema and feature-computation versions.
- Missingness by feature.
- Duplicate and data-quality decisions.
- Training, validation, and test boundaries.
- Sanitization status for any shareable artifact.
- Hashes of private local inputs when reproducibility requires them.

Private input hashes identify exact local inputs without publishing their contents. They must not
encode private filenames or account identifiers.

## Experiment register

| ID | Title | Status | Dataset | Primary decision |
| --- | --- | --- | --- | --- |
| EXP-000 | Experimental protocol baseline | Completed | None | Establish rules before model evaluation |
| EXP-001 | Activity and performance label audit | Proposed | Pending import | Determine whether race-time modeling is eligible |
| EXP-002 | Deterministic race-prediction baselines | Proposed | Pending EXP-001 | Quantify Riegel and recent-performance error |
| EXP-003 | Regularized race-time residual model | Proposed | Pending EXP-001 and EXP-002 | Test improvement over deterministic baselines |
| EXP-004 | Readiness-classification feasibility | Proposed | Pending label audit | Contingency only if a defensible observable label exists |
| EXP-005 | Coaching workflow evidence fidelity | Proposed | Synthetic and sanitized cases | Verify recommendation traceability and safety |

No row marked `Proposed` represents an empirical result.

## EXP-000: Experimental protocol baseline

### Status

Completed as a documentation decision. No athlete dataset was analyzed.

### Question

What minimum controls must apply before RunCoach AI reports a model result?

### Decision

The project requires:

- A versioned dataset manifest.
- Chronological evaluation.
- Deterministic and simple baselines.
- Leakage checks.
- Explicit model-eligibility gates.
- Error metrics in interpretable time units.
- Uncertainty and limitations with every prediction.
- A negative-result policy.

### Result

The protocol was adopted. This is a methodological result, not a predictive-performance result.

## EXP-001: Activity and performance label audit

### Status

Proposed. Execution begins only after representative Garmin and Strava exports are obtained and
inspected safely.

### Motivation

The athlete recalls approximately 11 races from the current challenge, plus earlier races, time
trials, and maximum-effort workouts. This recollection is not yet a verified label count. A
race-only dataset may be too small or inconsistent for a reliable learned model.

### Questions

- How many unique candidate performance events exist after cross-source deduplication?
- Which events have verified distance, elapsed time, date, and effort classification?
- Which events are races, time trials, maximum efforts, workouts, or ambiguous?
- How much pre-event training history is available for each candidate observation?
- Which sensor-derived candidate features have adequate coverage?
- Are labels distributed across distance and time, or concentrated in one period?
- Can a chronological holdout contain enough independent observations for evaluation?

### Inputs

- Imported and deduplicated activities.
- Source provenance and data-quality findings.
- Manual event-verification decisions.
- Verified reference performances retained as context, not automatically as model labels.

### Planned outputs

- Label-audit table.
- Eligibility and exclusion reason for every candidate event.
- Feature-coverage report.
- Chronological label distribution.
- Dataset manifest identifier.
- Recommendation to approve, revise, or reject the provisional target.

### Acceptance rule

Race-time modeling proceeds only if the audit supports a chronological evaluation that is more
informative than reporting a fitted result on nearly all available events. No fixed minimum count
is invented in advance; the decision must consider label independence, distance coverage,
temporal coverage, and uncertainty.

### Results

Not available. The activity exports have not yet been inspected.

## EXP-002: Deterministic race-prediction baselines

### Status

Proposed and dependent on EXP-001.

### Question

How accurately do deterministic and simple historical baselines predict later verified
performance events using only information available before each event?

### Baselines

1. Riegel prediction from the best eligible prior performance.
2. Most recent eligible same-distance performance.
3. Median or recency-weighted central estimate of eligible prior same-distance performances.

The Riegel formula is:

```text
T2 = T1 * (D2 / D1) ^ k
```

`T1` and `D1` describe a verified prior performance, `D2` is the target distance, and `k` is a
documented exponent. Any personalized exponent must be estimated from training data only.

### Evaluation

- Walk-forward chronological predictions.
- Mean absolute error in seconds.
- Median absolute error in seconds.
- Mean absolute percentage error.
- Signed error to detect systematic optimism or pessimism.
- Error grouped by target distance when sample size permits.

### Results

Not available.

## EXP-003: Regularized race-time residual model

### Status

Proposed and not yet eligible.

### Hypothesis

A small, regularized model using pre-event training and performance history may reduce
chronological prediction error relative to the applicable deterministic baseline.

### Target

The provisional target is the log residual between observed race time and a Riegel baseline
calculated only from prior eligible performances.

### Candidate models

- Ridge regression as the primary learned model.
- Elastic Net as a sparsity-aware comparison.
- A constrained tree-based model only if the sample size and evaluation design support it.

### Candidate feature families

- Target distance and event context known before the start.
- Prior verified performance summaries.
- Recent running volume and duration.
- Acute and chronic workload indicators.
- Fitness, fatigue, and form indicators.
- Recent intensity distribution.
- Long-run and consistency summaries.
- Heart-rate and cadence summaries when coverage is adequate.
- Missingness and source-coverage indicators.

### Eligibility gates

- EXP-001 approves the target and evaluation design.
- EXP-002 produces valid baseline predictions.
- Every feature is computable using pre-event data only.
- The pipeline can be fitted independently inside each chronological training window.
- Test observations remain untouched until the protocol is fixed.

### Decision rule

The learned model is eligible for coaching use only if it improves an agreed primary chronological
metric over the strongest applicable baseline and does not achieve that improvement through
leakage, unstable preprocessing, or a small number of unexplained outliers.

### Results

Not available.

## EXP-004: Readiness-classification feasibility

### Status

Proposed contingency. It is not an approved replacement target.

### Purpose

Evaluate whether the available history contains an observable and non-circular readiness label if
race-time prediction is rejected by EXP-001.

### Prohibited target construction

The target must not be a readiness score generated from the same workload rules used as features.
Self-reported readiness may be used only if it was recorded prospectively and consistently.
Injury diagnosis is not an acceptable target.

### Acceptance rule

Proceed only when the audit identifies enough chronological, independently observed labels and a
real decision supported by the classification output.

### Results

Not available.

## EXP-005: Coaching workflow evidence fidelity

### Status

Proposed.

### Question

Does the controlled coaching workflow preserve deterministic evidence, uncertainty, and safety
constraints across normal, missing-data, conflicting-evidence, and provider-failure scenarios?

### Dataset

Synthetic cases and approved sanitized cases only.

### Evaluation dimensions

- Evidence identifiers cited by recommendations.
- Numeric agreement with deterministic services.
- Preservation of data-quality limitations.
- Correct fallback when ML is ineligible.
- Rejection of medical or diagnostic language.
- Schema validity.
- Determinism when the LLM provider is disabled.
- Safe behavior on provider timeout or invalid output.

### Metrics

- Contract pass rate.
- Unsupported numeric-claim count.
- Safety-rule violation count.
- Evidence-citation coverage.
- Fallback success rate.

### Results

Not available.

## Standard experiment entry template

Copy this section for each new experiment:

```yaml
experiment_id: EXP-NNN
title: ""
status: proposed
registered_at_utc: ""
started_at_utc: null
completed_at_utc: null
git_commit: ""
dataset_manifest_id: ""
research_question: ""
hypothesis: ""
target_definition: ""
eligibility_rules: []
exclusion_rules: []
feature_set_version: ""
split_strategy: ""
baselines: []
candidate_models: []
primary_metric: ""
secondary_metrics: []
random_seed: null
artifact_paths: []
results: null
limitations: []
decision: ""
follow_up: []
```

## Model comparison template

| Experiment | Model | Train observations | Test observations | MAE seconds | Median AE seconds | MAPE | Signed error seconds | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Pending | Riegel | - | - | - | - | - | - | Not evaluated |
| Pending | Recent same-distance | - | - | - | - | - | - | Not evaluated |
| Pending | Historical central estimate | - | - | - | - | - | - | Not evaluated |
| Pending | Ridge residual model | - | - | - | - | - | - | Not evaluated |

## Reproducibility checklist

Before marking an experiment completed, confirm:

- The working tree revision is recorded.
- The dependency lockfile is unchanged or its change is documented.
- The dataset manifest exists.
- Private inputs can be identified locally without being committed.
- Feature definitions and units are versioned.
- Random seeds are recorded where applicable.
- Temporal split boundaries are recorded.
- Training-only preprocessing is verified.
- Baselines and candidate models use the same eligible observations.
- Metrics can be regenerated from stored predictions.
- Artifacts contain no secrets or identifying GPS data.
- Conclusions match the measured evidence.

## Negative and inconclusive results

A learned model that does not outperform Riegel remains an important result. The record must state
whether the likely cause is limited labels, feature coverage, instability, target construction,
distribution shift, or genuine absence of improvement.

An inconclusive experiment must not be rewritten as evidence of effectiveness. The deterministic
baseline remains the operational fallback until a later experiment passes the eligibility gates.

## Change protocol

Changes to a completed experiment require a new experiment identifier when they affect:

- Target or label definition.
- Eligibility or exclusion rules.
- Feature computation.
- Split boundaries.
- Preprocessing.
- Baseline selection.
- Model class or hyperparameter search.
- Primary evaluation metric.

Typographical corrections may be made in place when they do not change the protocol or result.

## Evidence retained for reporting

For every completed experiment, retain:

- Dataset-flow diagram or manifest summary.
- Label and missingness counts.
- Baseline and candidate-model metrics.
- Prediction-versus-observation plot.
- Residual analysis.
- Chronological split visualization.
- Feature definitions and leakage audit.
- Limitations and decision.
- Reproduction command.

All shareable evidence must use sanitized labels and non-identifying identifiers.

## Current next experiment

EXP-001 is the next eligible experiment. Its execution is blocked only by the absence of inspected
Garmin and Strava exports. No race-time model result should be claimed before that audit.
