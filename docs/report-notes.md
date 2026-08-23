# Graduation Report Notes

## Status

- Document type: Living report-development record
- Initial version: 2026-08-23
- Intended output: A technically rigorous report supported by reproducible project evidence
- Writing rule: Convert validated evidence into final prose; do not turn planned work into results

## Working title

**RunCoach AI: A Privacy-Aware Data Engineering and Intelligent Coaching Platform for Longitudinal
Running Performance Analysis**

Alternative concise title:

**RunCoach AI: Evidence-Grounded Running Analytics, Performance Prediction, and Coaching**

## Central argument

A useful personal running-coaching platform requires more than visualization or language-model
generation. It requires a reproducible pipeline that reconciles heterogeneous activity exports,
preserves provenance, calculates deterministic training evidence, evaluates predictive methods
honestly, and constrains generated recommendations to validated evidence and safety rules.

The strongest contribution is the integration of these concerns into one coherent, testable system.

## Research question

How can a privacy-aware data platform integrate heterogeneous Garmin and Strava activity exports,
derive reproducible training and performance indicators, evaluate personalized race-readiness and
prediction methods, and generate traceable coaching recommendations for a single athlete?

## Supporting questions

1. How can heterogeneous exported activities be validated, normalized, deduplicated, and retained
   with source provenance?
2. Which deterministic workload, fitness, fatigue, form, progression, and readiness indicators can
   be calculated transparently from the available data?
3. Does the audited activity history support a defensible learned prediction problem?
4. If eligible, can a learned model improve chronological race-time prediction over Riegel and
   simple recent-performance baselines?
5. How can a controlled agent workflow turn calculated evidence into recommendations without
   delegating authoritative calculations or safety decisions to a language model?
6. How can the platform be tested, containerized, and deployed without exposing private activity
   files or credentials?

## Intended contributions

### Engineering contribution

- Adapter-based ingestion of inspected Garmin and Strava export formats.
- Canonical relational model with provenance and cross-source deduplication.
- Versioned deterministic analytics and race-readiness evidence.
- Reproducible experiment and model-evaluation pipeline.
- Controlled evidence contract for coaching recommendations.
- Containerized local operation, automated quality gates, and sanitized cloud deployment.

### Analytical contribution

- Longitudinal analysis of one athlete across uneven platform and sensor coverage.
- Explicit separation of observed values, derived indicators, predictions, and explanations.
- Chronological comparison of personalized ML with deterministic baselines when data eligibility
  permits it.
- Transparent treatment of insufficient data and negative results.

### Methodological contribution

- Traceability from raw source through normalization, features, prediction, and recommendation.
- Leakage-aware evaluation for personal time-series data.
- Safety and privacy controls for LLM-assisted interpretation.
- Clear distinction between data-engineering practice and genuine Big Data scale.

## Research method

The report can frame the work as design-and-evaluation research supported by a longitudinal
single-athlete case study.

The method consists of:

1. Define the problem, requirements, intended use, and non-goals.
2. Design a modular architecture and canonical data model.
3. Inspect representative real exports before finalizing adapters.
4. Implement ingestion with validation, provenance, and idempotency.
5. Implement deterministic analytical methods with golden tests.
6. Audit labels and feature coverage.
7. Pre-register and execute eligible prediction experiments.
8. Integrate evidence into a controlled coaching workflow.
9. Evaluate correctness, reproducibility, privacy, failure behavior, and deployment.
10. Analyze limitations and threats to validity.

This is an applied system study. It does not claim population-level coaching effectiveness.

## Report structure

### 1. Abstract

Cover in compact form:

- The fragmented-data problem.
- The integrated platform contribution.
- The evaluation approach.
- The principal measured results.
- The main limitation.

Write the abstract after results are final. Do not include planned features.

### 2. Introduction

Explain:

- Why longitudinal running data is difficult to use across platforms.
- Why a dashboard alone is insufficient.
- Why deterministic analytics and controlled AI have different responsibilities.
- The research question and contributions.
- The report structure.

Evidence to retain:

- Concise source-history description.
- Primary and following race goals.
- System context diagram.

### 3. Background and related work

Organize by problem rather than by software product:

- Endurance-performance prediction and the Riegel model.
- Training-load concepts and impulse-response interpretations.
- Acute and chronic workload indicators and their interpretation limits.
- Personal time-series modeling and temporal validation.
- Sports-data interoperability and sensor-quality issues.
- Explainable recommendation systems.
- Tool-using or graph-controlled language-model workflows.
- Privacy risks in location and wearable data.
- Reproducible data and ML systems.

Use primary papers, official technical documentation, and critical reviews. Separate evidence for
physiological claims from evidence about software architecture.

### 4. Problem analysis and requirements

Base this chapter on:

- `docs/problem-statement.md`
- `docs/requirements.md`
- `docs/assumptions-and-limitations.md`

Include:

- Actors and intended use.
- Functional and non-functional requirements.
- Privacy boundaries.
- Success criteria.
- Explicit non-goals.
- Requirements traceability approach.

### 5. Architecture and design

Base this chapter on:

- `docs/architecture.md`
- `docs/data-model.md`
- Architecture decision records.

Explain:

- Why the baseline is a modular monolith.
- Module and process boundaries.
- Import, analytics, ML, and coaching data flows.
- PostgreSQL schema and provenance.
- Configuration, migrations, and health checks.
- Technology selection and measurable adoption triggers.
- Privacy boundaries between local, CI, cloud, and LLM contexts.

Avoid presenting a technology list without linking each component to a requirement.

### 6. Data ingestion and quality

Document only after inspecting real exports.

Include:

- Export acquisition procedure.
- Observed file hierarchy and formats.
- Parser-adapter contracts.
- Units, timezones, timestamps, and source identifiers.
- Validation severities.
- Canonicalization.
- Deduplication evidence and ambiguity handling.
- Transactional import and idempotency.
- Provenance from canonical records to source files.
- Data-quality and feature-coverage results.

Suggested evidence:

- Sanitized source-schema table.
- Import sequence diagram.
- Import state transition diagram.
- Duplicate examples with identifying fields removed.
- Counts before and after validation and deduplication.

### 7. Deterministic analytics

For every method, report:

- Definition and units.
- Required inputs.
- Missing-data behavior.
- Parameter choice.
- Initialization behavior.
- Method version.
- Test oracle or independently calculated example.
- Interpretation boundary.

Cover:

- Pace and speed.
- Weekly distance, duration, and elevation.
- Heart-rate and intensity distribution.
- Load measures.
- Fitness, fatigue, and form indicators.
- Personal-best progression.
- Riegel race-time baseline.
- Readiness components and evidence.

Do not describe modeled indicators as direct physiological measurements.

### 8. Machine-learning methodology and experiments

Base this chapter on:

- `docs/ml-methodology.md`
- `docs/experiment-log.md`
- Versioned dataset and experiment manifests.

Required narrative:

- Why the label audit precedes target approval.
- Observation and target definition.
- Candidate features and leakage controls.
- Chronological split strategy.
- Baselines and candidate models.
- Metrics and uncertainty.
- Eligibility gates.
- Results, including negative or inconclusive results.
- Threats to internal, external, construct, and conclusion validity.

The report must not claim that a learned model is useful unless it passes its registered comparison.

### 9. Controlled coaching workflow

Base this chapter on `docs/agent-workflow.md`.

Explain the five responsibilities:

1. Data-quality gate.
2. Training-load analysis.
3. Performance prediction.
4. Coaching explanation.
5. Safety and consistency review.

Show why each responsibility is separate and which steps are deterministic. Include the evidence
contract, graph routing, fallback behavior, provider abstraction, and audit record.

Evaluate evidence fidelity and safety, not only fluency.

### 10. Implementation and verification

Cover:

- Package structure and module boundaries.
- API contracts.
- SQLAlchemy and Alembic practices.
- Streamlit-to-API interaction.
- Configuration and secret handling.
- Test pyramid and test-data policy.
- Formatting, linting, strict typing, and coverage gates.
- Container build and health verification.
- CI pipeline.

Use exact commands and evidence from a clean revision.

### 11. Deployment and operational evaluation

Base this chapter on `docs/deployment.md`.

Include:

- Local and cloud topology.
- Sanitized demo-data boundary.
- Migration and release procedure.
- Liveness and readiness behavior.
- Logging and error-sanitization rules.
- Cost and operational constraints.
- Cloud smoke-test evidence.
- Recovery or rebuild test.

### 12. Results and discussion

Separate results from interpretation.

Suggested result groups:

- Import correctness and data-quality findings.
- Historical coverage and missingness.
- Deterministic analytical outputs.
- Baseline prediction error.
- ML eligibility and comparison result.
- Coaching workflow contract and safety results.
- Test, CI, and deployment results.

Discuss what the evidence supports, what it does not support, and which architectural decisions were
validated or challenged.

### 13. Threats to validity and limitations

Use `docs/assumptions-and-limitations.md` as the source register.

Organize threats as:

- Internal validity.
- External validity.
- Construct validity.
- Conclusion validity.
- Data and measurement limitations.
- Privacy and operational limitations.

Describe mitigations without pretending they remove every threat.

### 14. Conclusion and future evolution

Answer the research question directly. Summarize validated contributions, not implemented file
counts or technology names.

Future evolution should be tied to observed needs, such as:

- Additional athletes for external validation.
- Prospective wellness and readiness labels.
- Course and weather context.
- Authenticated private deployment.
- Continuous ingestion.
- Event streaming or independent services when measured requirements warrant them.

## Research-question traceability

| Question | System evidence | Evaluation evidence | Planned report section |
| --- | --- | --- | --- |
| Heterogeneous data integration | Adapters, canonical schema, provenance, deduplication | Parser, import, database, and end-to-end tests | Data ingestion and quality |
| Deterministic training evidence | Versioned analytics services | Golden tests and coverage reports | Deterministic analytics |
| Predictive value | Dataset builder and model pipeline | Chronological baseline comparison | ML methodology and experiments |
| Controlled recommendations | Agent graph and evidence contract | Contract, fallback, and safety tests | Controlled coaching workflow |
| Privacy-aware deployment | Ignore rules, sanitization, container boundary | Image, secret, and cloud checks | Deployment and operations |

## Technology explanation template

Use this pattern for every major technology:

| Question | Required answer |
| --- | --- |
| Why selected? | Connect the technology to a specific requirement or quality attribute |
| Concept demonstrated? | Identify the data, software, ML, AI, or cloud concept |
| Problem solved? | State the concrete failure or complexity it addresses |
| Simpler alternative? | Name a credible alternative and when it would be adequate |
| Limitation? | State operational, scientific, or maintenance cost |
| Adoption evidence? | State which tests, measurements, or artifacts validate the choice |

This prevents technology selection from becoming a list of tools used for appearance.

## Claim-discipline guide

Prefer:

- `The pipeline processed the inspected export variants...`
- `The indicator models recent workload under the documented method...`
- `The learned model reduced chronological MAE by...`
- `The system produced a non-medical warning indicator...`
- `The dataset applies data-engineering principles at the observed scale...`

Avoid:

- `The parser supports every Garmin export...` without coverage evidence.
- `Fitness was measured...` when it was modeled.
- `The model predicts injuries...`.
- `AI calculated the athlete's training load...`.
- `The system is Big Data...` solely because activity files are numerous.
- `The model is accurate...` without a metric, baseline, split, and uncertainty.

## Evidence register

Populate this table as evidence is produced:

| ID | Evidence | Source revision | Sanitized | Report use | Status |
| --- | --- | --- | --- | --- | --- |
| E-001 | Foundation quality-gate output | Pending | Yes | Implementation | Pending capture |
| E-002 | Healthy Compose topology | Pending | Yes | Deployment | Pending capture |
| E-003 | Export schema inventory | Pending | Required | Ingestion | Not available |
| E-004 | Import and deduplication counts | Pending | Required | Ingestion results | Not available |
| E-005 | Metric golden-test results | Pending | Yes | Analytics | Not available |
| E-006 | Label-audit report | Pending | Required | ML methodology | Not available |
| E-007 | Baseline and model comparison | Pending | Required | ML results | Not available |
| E-008 | Agent safety evaluation | Pending | Yes | Coaching workflow | Not available |
| E-009 | CI run | Pending | Yes | Verification | Pending capture |
| E-010 | Sanitized cloud smoke test | Pending | Yes | Deployment | Not available |

## Figure backlog

- System context diagram.
- Container and module diagram.
- Import data-flow diagram.
- Import-job state diagram.
- Entity-relationship diagram.
- Deduplication decision flow.
- Deterministic analytics flow.
- Chronological ML split diagram.
- Baseline-versus-model error plot.
- Fitness, fatigue, and form time series.
- Personal-best progression plot.
- Agent workflow and safety routing.
- Local and cloud deployment diagram.

Every figure needs a caption explaining its claim, not merely its contents.

## Table backlog

- Requirements traceability matrix.
- Source-format and field-coverage matrix.
- Canonical field and unit definitions.
- Validation-rule catalog.
- Metric method catalog.
- Label-audit summary.
- Feature schema.
- Model and baseline results.
- Agent test cases.
- Technology rationale.
- Assumptions and limitations.
- Deployment verification results.

## Literature-search notes

Verify and retain authoritative sources for:

- Riegel race-time scaling.
- Impulse-response training models.
- Training-load measurement and interpretation.
- Critiques of acute-to-chronic workload ratios.
- Heart-rate zone estimation.
- Temporal evaluation and leakage in predictive modeling.
- Wearable and GPS measurement reliability.
- Explainable and safety-constrained recommendation systems.
- LLM structured output and tool orchestration.
- Location-data privacy and anonymization.
- Reproducible ML experiment reporting.

Do not cite vendor marketing for scientific claims when primary literature is available.

## Current factual anchors

- Strava contains the longer historical record.
- Garmin provides richer recent data beginning in April 2026.
- Exact export formats and schemas remain uninspected.
- Current verified reference performances are 19:41 for 5K, 41:30 for 10K, 1:32:00 for the half
  marathon, and 3:42:00 for the marathon.
- Observed maximum heart rate is approximately 195 bpm.
- Lowest observed resting heart rate is approximately 45 bpm.
- Lactate-threshold heart rate has not been formally tested.
- The primary target is the Casablanca Half Marathon on 2026-10-25, initially targeting sub-1:30.
- The following major target is the Marrakech Marathon on 2027-01-31.
- The race-only ML sample may be insufficient and must be audited.
- Public cloud data must be sanitized or synthetic.

## Open decisions

- Which exact export variants will be supported after inspection?
- Which canonical fields can be populated consistently across historical periods?
- Which training-load method has adequate input coverage?
- Which heart-rate zone method is defensible without a tested threshold?
- Does the label audit approve race-time prediction?
- Which readiness components can be validated rather than merely displayed?
- Which cloud platform best satisfies the verified deployment requirements?
- Is LLM-backed output needed in the public demonstration, or is deterministic fallback clearer?

Record resolved architectural decisions as ADRs and experimental decisions in the experiment log.

## Reproducibility appendix checklist

- Repository URL and evaluated commit.
- Supported operating environment.
- Python and dependency versions.
- Environment-variable reference without secrets.
- Clean setup commands.
- Database migration commands.
- Test and quality commands.
- Sanitized fixture provenance.
- Dataset-manifest structure.
- Experiment reproduction commands.
- Container build and deployment commands.
- Known platform-specific behavior.

## Report completion criteria

The report is ready for submission when:

- Every implemented claim links to source or evidence.
- Every numerical result can be reproduced.
- Planned work is not presented as completed.
- Private data and credentials are absent.
- Diagrams agree with the deployed system.
- Requirements, implementation, tests, and conclusions are traceable.
- Model results include baselines, chronological evaluation, and limitations.
- Coaching claims preserve the deterministic and medical-safety boundaries.
- Big Data claims match measured scale.
- Limitations and negative results remain visible.
