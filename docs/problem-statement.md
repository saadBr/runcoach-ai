# Problem Statement

## Status

- Project: PaceCraft AI
- Document state: Initial approved baseline
- Last updated: 2026-08-23

## Context

Consumer running platforms collect valuable activity information, but an athlete's history may
be fragmented across providers, export formats, sensor coverage, and time periods. In this
case study, Strava contains the longer historical record, while Garmin provides richer recent
sensor data beginning in April 2026.

Existing platforms expose summaries and proprietary indicators, but they do not provide a
fully inspectable research pipeline in which ingestion rules, data-quality decisions,
deduplication, training calculations, machine-learning experiments, and recommendation
evidence can all be reproduced and defended academically.

## Problem

The project must determine how heterogeneous personal running exports can be transformed
into a trustworthy analytical record and then used to produce explainable performance and
coaching support.

A useful solution must address several connected problems:

1. Import real Garmin and Strava exports without depending on private Garmin API access.
2. Identify malformed, incomplete, and duplicate activities without destroying source
   provenance.
3. Normalize activity, lap, GPS, heart-rate, cadence, elevation, and derived information.
4. Calculate workload, trend, personal-best, and race-readiness indicators using deterministic
   and testable algorithms.
5. Evaluate whether a carefully scoped machine-learning model adds value beyond a
   deterministic race-time baseline.
6. Generate recommendations that cite validated evidence and do not make medical claims.
7. Protect private activity files and credentials throughout local development and cloud
   demonstration.

## Research question

How can a modular, reproducible data and machine-learning platform integrate heterogeneous
Garmin and Strava exports to produce transparent running-performance indicators and
evidence-backed coaching recommendations for a single athlete?

## Supporting questions

- Which validation and deduplication rules produce a reliable canonical activity history?
- How should differences in historical sensor coverage affect workload calculations and
  confidence?
- Can personalized features improve race-time estimation beyond a Riegel baseline with the
  available number of verified performances?
- How can a controlled agent workflow explain results without replacing deterministic
  calculations or overstating injury risk?
- Which data-engineering and cloud practices are valuable at personal-data scale, and which
  distributed technologies would be unjustified?

## Project objectives

- Build a reproducible ingestion pipeline for inspected Garmin and Strava export formats.
- Create an auditable PostgreSQL data model with source provenance and versioned metrics.
- Implement deterministic training-load, trend, personal-best, and race-readiness analysis.
- Conduct one leakage-aware machine-learning experiment with chronological evaluation.
- Implement a controlled coaching workflow with data-quality and safety gates.
- Deliver tested local containers, CI, a sanitized cloud demonstration, and continuously
  maintained graduation documentation.

## Case-study goals

The initial athlete case study will evaluate readiness for:

- A half marathon on 2026-10-25 with an initial sub-1:30 target.
- A marathon on 2027-01-31.

These goals configure the evaluation context; they do not guarantee that a target is safe or
achievable.

## Academic contribution

The project demonstrates:

- Batch data ingestion and schema normalization.
- Data quality, lineage, idempotency, and reproducibility.
- Relational and time-series data modeling.
- Deterministic analytical modeling.
- Supervised machine-learning methodology and baseline comparison.
- Controlled AI-agent orchestration and guardrails.
- Containerization, CI/CD, and cloud deployment.

The project applies Big Data and cloud-computing principles but does not claim genuine Big
Data scale. Personal activity volume does not require distributed storage or computation.

## Success criteria

The project is successful when:

- Real inspected exports can be imported reproducibly without duplicate canonical activities.
- Every important metric identifies its inputs, method, version, and data coverage.
- The dashboard explains trends and readiness components rather than showing opaque scores.
- The ML experiment reports honest temporal-validation results against deterministic
  baselines.
- Coaching recommendations reference stored evidence and pass safety checks.
- A new developer can reproduce the tested local system from the repository instructions.
- The public cloud demonstration contains no raw private activity data or credentials.

## Boundaries

PaceCraft AI is a coaching-support and academic research prototype. It is not:

- A medical device.
- An injury-diagnosis system.
- A substitute for a qualified coach or healthcare professional.
- A live tracking or emergency-response service.
- A claim of statistically valid population-level sports science.
