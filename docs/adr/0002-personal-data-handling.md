# ADR-0002: Keep Raw Personal Activity Data Local and Publish Only Approved Sanitized Data

## Status

Accepted

## Date

2026-08-23

## Decision owners

PaceCraft AI project team and data owner

## Context

Garmin and Strava exports can contain highly identifying information, including:

- Exact GPS routes and repeated home or work locations.
- Activity timestamps and personal routines.
- Athlete names, usernames, email addresses, and account identifiers.
- Device identifiers and serial numbers.
- Activity titles, descriptions, notes, and social metadata.
- Health-adjacent measurements such as heart rate and resting heart rate.
- Race participation and performance history.
- API credentials or export links if handled carelessly.

The application needs real personal data for local analysis, but its source repository, CI system,
cloud demonstration, report, and presentation must remain safe to share.

Repository ignore rules reduce accidental commits but do not define a complete data-handling model.
A deliberate boundary is required for storage, processing, sanitization, language-model context,
logging, testing, deployment, and evidence capture.

## Decision drivers

- Protect the athlete's identity, location, routines, and credentials.
- Preserve the ability to analyze real exported data locally.
- Keep source control and CI shareable.
- Support a public sanitized demonstration.
- Retain reproducible provenance without publishing raw files.
- Minimize data sent to external language-model providers.
- Make privacy behavior testable and reviewable.
- Avoid claiming formal anonymity when re-identification risk remains.

## Decision

Raw personal activity data is classified as private and remains in explicitly ignored local storage.
It must not be committed to Git, embedded in container images, copied to CI, uploaded to the public
cloud demonstration, or included in report and presentation artifacts.

Only synthetic data or data that passes the documented automated and manual sanitization process may
be used in shareable fixtures, cloud databases, screenshots, reports, or presentations.

Secrets are supplied through runtime environment variables or the selected platform's secret
facility. They must not be stored in source-controlled configuration.

The LLM boundary receives the minimum validated structured evidence needed for explanation. Raw
files, raw GPS tracks, credentials, and unnecessary identifiers are not sent to an LLM by default.

## Data classification

| Class | Examples | Repository | CI | Public cloud | LLM context |
| --- | --- | --- | --- | --- | --- |
| Secret | API keys, database passwords, tokens | Never | Injected only when approved | Secret store only | Never |
| Raw private | FIT, GPX, TCX, CSV exports, ZIP archives | Never | Never | Never | Never |
| Canonical private | Local activities, exact timestamps, coordinates, health-adjacent data | Never as data | Never | Never | Minimal aggregates only when approved |
| Derived private | Personal loads, readiness, predictions, recommendations | Never as data | Synthetic equivalents | Never unless sanitized | Selected evidence only |
| Sanitized | Reviewed records without identifying fields or routes | Allowed as approved fixture | Allowed | Allowed | Allowed when necessary |
| Synthetic | Generated records with no real-person source | Allowed | Allowed | Allowed | Allowed |
| Public code and docs | Source, schemas, methods, diagrams | Allowed | Allowed | Allowed | Not applicable |

Classification is based on content, not filename. Renaming a raw export does not make it sanitized.

## Repository boundary

The repository must ignore:

- `.env` and environment-specific secret files.
- Raw export directories.
- FIT, GPX, TCX, CSV export patterns, and ZIP archives.
- Local databases and PostgreSQL volumes.
- Model artifacts or experiment outputs that may contain personal records.
- Logs and temporary files.

`.env.example` contains names and safe placeholders only.

The test-fixture exception applies only to manually approved sanitized or synthetic fixtures. Every
shareable fixture requires provenance notes and privacy review.

Before each release, inspect:

- `git status`.
- Staged file names.
- Staged text for credentials and private identifiers.
- Docker build context.
- Generated screenshots and experiment artifacts.

## Local storage boundary

Private exports belong under the configured local private-data directory, such as
`data/private`, which is ignored by Git.

Local handling rules:

- Preserve original exports as immutable source evidence where practical.
- Record a content hash for provenance and idempotency.
- Do not expose private directories through a static file server.
- Restrict filesystem permissions to the data owner.
- Treat local database backups as private.
- Avoid copying raw data into temporary directories outside the protected project location.
- Delete temporary extracted files when the import design no longer needs them.
- Protect device and cloud backups according to the same classification.

Local storage is permitted because the athlete is the data owner and local analysis is the intended
use. This decision does not remove the need for operating-system access controls and backups.

## Import handling

The import process must:

1. Read from an explicitly configured private location.
2. Identify the format from content and supported structure, not extension alone.
3. Hash the input without logging its full path publicly.
4. Parse with bounded resource use.
5. Validate before canonical persistence.
6. Store source provenance and sanitized error details.
7. Avoid writing raw content to application logs.
8. Commit canonical records and provenance transactionally.
9. Preserve ambiguous duplicate decisions for manual review.
10. Remove temporary extraction artifacts according to retention rules.

File upload names and archive paths are untrusted input. Prevent path traversal, archive expansion
abuse, oversized payloads, and parser-specific denial-of-service conditions.

## Database boundary

The local PostgreSQL database may contain private canonical and derived records.

Controls:

- Use local-only or restricted network access.
- Use credentials distinct from any cloud environment.
- Keep database dumps outside Git.
- Restrict coordinates and source metadata to authorized application paths.
- Record provenance and deletion state.
- Avoid returning private fields from broad API responses.
- Test serialization schemas for accidental field exposure.

The public cloud database must be created independently from migrations and an approved sanitized
seed. A local private database dump must never be restored into it.

## Sanitization pipeline

Sanitization is a reproducible transformation followed by manual review.

### Remove

- Names, usernames, email addresses, account IDs, and profile links.
- Device serial numbers and stable hardware identifiers.
- External activity identifiers.
- Activity titles, descriptions, comments, and free text unless replaced.
- Raw filenames and archive hierarchy.
- Exact GPS coordinates and route geometry.
- Authentication or authorization metadata.
- Photos and linked media.

### Transform or generalize

- Replace identifiers with generated demonstration identifiers.
- Shift or synthesize dates when exact routines are unnecessary.
- Reduce temporal precision where analytical behavior is preserved.
- Generalize location to a non-identifying region when needed.
- Aggregate trackpoints into non-identifying summary metrics.
- Perturb or synthesize values when rare performance patterns create re-identification risk.

### Retain only when needed

- Sport type.
- Duration and distance.
- Aggregate elevation.
- Aggregate heart rate and cadence.
- Derived workload and readiness indicators.
- Relative chronological order.
- Non-identifying goals and recommendation evidence.

### Validate

Automated checks must confirm the absence of:

- Coordinate fields and route polylines.
- Email and token patterns.
- Known private identifiers.
- Raw source filenames.
- Unexpected free-text fields.
- Secrets and connection strings.

Manual review must consider whether remaining dates, routes, rare races, performance combinations,
or text can be linked back to the athlete.

## Sanitization manifest

Each sanitized dataset must record:

```yaml
sanitization_id: ""
created_at_utc: ""
source_category: ""
source_hashes_private: true
sanitizer_version: ""
git_commit: ""
removed_fields: []
transformed_fields: []
retained_fields: []
automated_checks: []
record_count: 0
manual_reviewer: ""
manual_reviewed_at_utc: ""
residual_risks: []
publication_decision: rejected
```

Private source hashes may be recorded in a local manifest. A public manifest may refer to the local
manifest identifier without publishing linkable information.

## CI and test-data boundary

CI must operate without personal files, private database state, or developer credentials.

Permitted test data:

- Fully synthetic fixtures.
- Small, manually approved sanitized fixtures.
- Generated database records.
- Fake provider responses.

Every fixture derived from real data requires:

- A provenance note.
- A list of transformations.
- Automated privacy checks.
- Manual approval.
- Confirmation that exact GPS routes and stable identifiers are absent.

Network-backed provider tests must be explicitly separated from ordinary CI and must not transmit
private records.

## Docker boundary

The Docker build context must exclude private and generated data.

Verification must inspect that the image contains no:

- `.env` files.
- Export archives.
- FIT, GPX, TCX, or source CSV files.
- Local databases or dumps.
- Private logs.
- ML artifacts containing observations.
- Git history with accidentally removed secrets.

Runtime mounting of private data is local and explicit. No private directory is copied during image
build.

## Cloud boundary

The public cloud deployment uses:

- Sanitized or synthetic seed data.
- Separate cloud database credentials.
- Platform-managed HTTPS.
- Runtime secret injection.
- Restricted database network access.
- Upload and mutation features disabled unless access control is implemented.
- Logging configured to exclude sensitive fields.

The public environment is a separate data domain. It does not synchronize from the local private
database.

## LLM boundary

The default provider configuration is disabled.

When an LLM provider is enabled, the application sends only an approved structured evidence packet
containing the minimum necessary:

- Derived training summaries.
- Readiness components.
- Prediction outputs and limitations.
- Goal context needed for the requested explanation.
- Non-identifying evidence identifiers.

The following are not sent by default:

- Raw activity files.
- Trackpoint streams.
- GPS routes.
- Names or account identifiers.
- Database keys that can be resolved outside the application.
- Credentials.
- Unfiltered activity titles or notes.

Provider requests and responses must be logged only through sanitized audit metadata. Full prompts
or outputs require explicit local-only diagnostic handling and must not contain secrets.

## Logging and error handling

Logs may contain:

- Correlation identifiers.
- Import batch identifiers.
- Generated canonical identifiers.
- File content hash prefixes when not externally linkable.
- Parser type.
- Counts, durations, and sanitized error categories.

Logs must not contain:

- Credentials or connection URLs.
- Raw file contents.
- Exact private paths in shareable output.
- GPS coordinates.
- Athlete or account names.
- Full external activity identifiers.
- Unfiltered provider prompts.

Public API errors return stable codes and sanitized messages. Detailed private diagnostics remain in
protected local logs when required.

## Reports, screenshots, and presentation artifacts

All shareable evidence must be reviewed as data, not treated as harmless documentation.

Before inclusion:

- Crop browser and terminal chrome that may contain identity or tokens.
- Remove private paths and usernames.
- Replace database and activity identifiers.
- Verify maps and coordinates are absent or synthetic.
- Verify dates do not disclose private routines.
- Use approved sanitized dashboard data.
- Remove cloud connection details.
- Confirm image metadata does not retain identifying information.

## Retention and deletion

Retention rules must distinguish:

- Immutable source exports needed for local reproducibility.
- Temporary extracted files.
- Canonical local database records.
- Generated experiment artifacts.
- Sanitized demonstration datasets.
- Cloud logs and backups.

At minimum:

- Temporary extraction artifacts are deleted after successful import unless required for an
  explicitly documented recovery process.
- Cloud demonstration data can be rebuilt from migrations and approved seed data.
- Deleted local activities retain only the minimum tombstone or audit information required for
  deduplication and traceability.
- Backups follow the classification of their source.
- Material deletion is recorded with scope and recovery status.

## Threat model

| Threat | Example | Primary control |
| --- | --- | --- |
| Accidental Git commit | Raw GPX added with source code | Ignore rules, staged review, secret and privacy scans |
| Image leakage | Export copied into Docker layer | `.dockerignore` and image inspection |
| CI leakage | Test requires developer export | Synthetic fixtures and isolated CI configuration |
| Cloud leakage | Local dump restored to demo | Independent sanitized seed process |
| Location inference | Route reveals home address | Remove route geometry and coordinates |
| Linkage attack | Rare date and result identify athlete | Date transformation and manual review |
| Log leakage | Parser logs raw record | Structured allow-listed logging |
| Prompt leakage | Full activity stream sent externally | Minimal evidence contract and provider boundary |
| Credential leakage | API key committed or printed | Secret injection and log filtering |
| Archive attack | Malicious ZIP writes outside target | Safe extraction and resource limits |

## Options considered

### Store raw exports in Git Large File Storage

Not selected. Access control, repository cloning, history retention, and accidental sharing remain
poor fits for sensitive route and health-adjacent data.

### Upload the private database to the cloud

Not selected for the public environment. It increases exposure without being required to
demonstrate product behavior.

### Use only synthetic data everywhere

Not selected. Real local exports are necessary to evaluate heterogeneous ingestion and longitudinal
personal analytics. Synthetic data remains appropriate for CI and public demonstrations.

### Send full activity history to the LLM

Not selected. Deterministic services can calculate evidence locally, and minimal structured context
reduces privacy, cost, and hallucination risk.

### Local private analysis plus sanitized public data

Selected. It preserves real-data value while maintaining a shareable repository and cloud boundary.

## Consequences

### Positive

- Raw location and health-adjacent data remain under the data owner's control.
- The repository and CI remain safe to share.
- The cloud demonstration can be public without containing the private database.
- Provider context is minimized.
- Privacy behavior can be tested.
- Provenance remains reproducible through local manifests and hashes.

### Negative

- The public demonstration cannot prove raw-file ingestion directly when upload is disabled.
- Sanitization requires implementation, automated checks, and manual review.
- Some realistic route-based features cannot appear publicly.
- Reproducing private experiments requires access to the data owner's local inputs.
- Sanitized values may reduce realism or analytical consistency.

### Residual risks

- A rare combination of dates and performances may remain linkable.
- Local device compromise can expose files.
- Human review can miss identifying details.
- Third-party provider policies and behavior may change.
- Deleted secrets remain in Git history if committed before detection.

These risks require ongoing review; sanitization is risk reduction, not a guarantee of anonymity.

## Verification

The decision is verified through:

- Repository-ignore tests and staged-file review.
- Secret scanning.
- Docker build-context and image inspection.
- Fixture provenance checks.
- Sanitization unit and property tests.
- Searches for coordinates, identifiers, emails, and token patterns.
- API schema tests for private-field exposure.
- LLM contract tests asserting minimal context.
- Cloud database inspection.
- Manual review of every published dataset and screenshot.

## Incident response

If private data or a secret is exposed:

1. Stop publication or deployment access.
2. Identify the exact affected artifact and exposure window.
3. Revoke and rotate exposed credentials immediately.
4. Remove the artifact from active distribution.
5. Determine whether Git history, image registries, CI logs, backups, or caches retain it.
6. Follow platform-specific purge procedures.
7. Record the incident without repeating the sensitive value.
8. Add a preventive test or control.
9. Notify affected parties when required.

Deleting a file in a later commit is not sufficient if the sensitive content remains in history.

## Revisit conditions

Review this ADR when:

- Authenticated remote private use is introduced.
- Multiple athletes are supported.
- Object storage is introduced for raw exports.
- Direct platform API ingestion is enabled.
- A new external model or analytics provider receives athlete data.
- Route visualization becomes remotely available.
- Applicable legal or institutional requirements change.
- Sanitized data is proposed for publication beyond the demonstration.

## Related documents

- `.gitignore`
- `.dockerignore`
- `.env.example`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/data-model.md`
- `docs/testing-strategy.md`
- `docs/deployment.md`
- `docs/assumptions-and-limitations.md`
