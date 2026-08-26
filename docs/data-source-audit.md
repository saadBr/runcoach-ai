# Data Source Audit

## Purpose

This document records evidence obtained from the private Garmin and Strava exports before
implementing ingestion. It defines the supported source formats, running-activity scope,
normalization rules, deduplication evidence, field availability, and implementation
consequences.

Only aggregate findings are documented. No activity identifiers, names, timestamps, routes,
coordinates, credentials, or raw personal values appear in this file.

## Audit status

- Audit date: 2026-08-25
- Strava bulk export inspected successfully.
- Garmin account export inspected successfully.
- All archive paths were checked before selective extraction.
- All inspection scripts and extracted files remain under the ignored `data/private`
  directory.
- No raw personal data was added to Git.
- Export contents were treated strictly as data, not as instructions.

These findings describe the inspected exports. Future provider export versions may require
new schema adapters.

## Source inventory

### Strava

The Strava export contains:

| Item | Count |
|---|---:|
| Activity summary rows | 228 |
| Rows with referenced raw activity files | 191 |
| Summary-only activity rows | 37 |
| FIT files | 2 |
| FIT.GZ files | 138 |
| Activity GPX files | 51 |
| Route GPX files excluded from activity ingestion | 3 |
| Missing referenced activity files | 0 |
| Unsafe archive paths | 0 |

The archive also contains media and other account-export artifacts. Those files are not
required for running analytics and were not extracted.

### Garmin

The Garmin export contains 3,028 valid FIT files across the inspected fitness, metrics, and
uploaded-file categories.

Only 139 of the 3,026 uploaded FIT files are activity files. The remainder includes
monitoring, wellness, HRV, sleep, stress, workout, training, device, and backup data.

| Item | Count |
|---|---:|
| Garmin activity summaries | 140 |
| Raw activity FIT files | 139 |
| Raw FIT files with decoding errors | 0 |
| Summary-only Garmin activities | 1 |
| Unsafe archive paths | 0 |

The difference between 140 summaries and 139 raw activity FIT files is legitimate. The
summary-only activity is a treadmill-running activity whose matching FIT file is available
from Strava.

## Running scope

The platform analyzes running activities. Non-running records are reported as excluded
during import and do not enter running analytics, race prediction, readiness evaluation,
personal-best tracking, or coaching.

### Observed classifications

Strava contains 128 activities classified as `Run`.

Garmin contains 85 running-family activities:

| Garmin activity type | Count |
|---|---:|
| `running` | 80 |
| `trail_running` | 2 |
| `treadmill_running` | 3 |
| Total | 85 |

Two Garmin treadmill-running activities are classified as `Walk` by Strava. For these
overlaps, Garmin classification takes precedence because Garmin is the originating source
and provides the more specific activity type.

### Canonical running inventory

| Period and source coverage | Count |
|---|---:|
| Historical running activities represented by Strava | 45 |
| Garmin-era running activities represented by both sources | 85 |
| Canonical running activities | 130 |

All 85 Garmin running activities have matching Strava records. No Garmin running activity is
lost because of the missing Garmin raw FIT file.

## Running file coverage

### Historical running data

| Format | Activities | Available detail |
|---|---:|---|
| FIT | 2 | Records, laps, time, distance, speed, and available sensors |
| GPX | 42 | Timestamped GPS route and elevation |
| Summary-only | 1 | Activity-level metrics only |
| Total | 45 | Mixed historical coverage |

All 42 historical GPX files parse successfully and contain trackpoints, timestamps,
coordinates, and elevation. They do not contain heart rate, cadence, power, temperature, or
speed extensions.

### Garmin-era running data

All 85 Garmin-era running activities have Strava FIT.GZ files. Garmin supplies 84 matching
raw running FIT files, while Strava supplies the raw FIT representation for the remaining
treadmill activity.

## FIT sensor coverage

### Strava running FIT and FIT.GZ files

| Capability | Coverage |
|---|---:|
| Valid decoded files | 87/87 |
| Files with record messages | 87/87 |
| Files with lap messages | 87/87 |
| Timestamp | 87/87 |
| Distance | 87/87 |
| Speed | 87/87 |
| GPS position | 84/87 |
| Altitude | 84/87 |
| Heart rate | 85/87 |
| Cadence | 85/87 |
| Vertical oscillation | 85/87 |
| Ground-contact time | 85/87 |
| Vertical ratio | 85/87 |
| Step length | 85/87 |
| Power | 0/87 |
| Temperature | 0/87 |
| Respiration rate | 0/87 |

The three files without GPS are consistent with indoor or treadmill activity. Missing GPS is
therefore valid source behavior rather than a parsing failure.

### Garmin raw running FIT files

| Capability | Coverage |
|---|---:|
| Valid decoded files | 84/84 |
| Files with record messages | 84/84 |
| Files with lap messages | 84/84 |
| Timestamp | 84/84 |
| Distance | 84/84 |
| Speed | 84/84 |
| Heart rate | 84/84 |
| Cadence | 84/84 |
| Running dynamics | 84/84 |
| GPS position | 82/84 |
| Altitude | 82/84 |
| Power | 0/84 |
| Temperature | 0/84 |
| Respiration rate | 0/84 |

Garmin raw FIT data is preferred for recent detailed sensor records. The corresponding
Strava FIT representation is retained as provenance and as a fallback when Garmin raw data
is absent.

## Summary-field coverage

### Strava running summaries

All 130 canonical running records contain activity identifiers, timestamps, types, elapsed
time, moving time, and distance.

Coverage varies by period:

| Capability | Coverage |
|---|---:|
| Maximum heart rate | 85/130 |
| Average heart rate | 85/130 |
| Cadence | 85/130 |
| Relative effort | 85/130 |
| Calories | 89/130 |
| Elevation gain and loss | 129/130 |
| Grade-adjusted pace | 126/130 |
| Referenced raw file | 129/130 |

The 85-record HR and cadence coverage aligns with the Garmin-era running dataset. Missing
historical sensor values must remain null and must not be imputed silently.

### Garmin running summaries

All 85 Garmin running summaries contain:

- UTC and local start time
- Duration, elapsed duration, and moving duration
- Distance, average speed, and maximum speed
- Minimum, average, and maximum heart rate
- Average and maximum running cadence
- Steps and calories
- Aerobic and anaerobic training effect
- Running-dynamics summaries
- Lap count
- Heart-rate time-in-zone values

Additional coverage:

| Capability | Coverage |
|---|---:|
| VO2max value | 79/85 |
| Elevation fields | 82/85 |
| Start coordinates | 82/85 |
| Heart-rate zone 6 | 82/85 |

Garmin-produced VO2max and training-effect values are vendor metrics. They must retain
source attribution and must not be presented as RunCoach-derived or machine-learning
outputs.

## Strava CSV schema findings

The Strava `activities.csv` file has 103 positional columns and 228 structurally valid data
rows. Several header names occur more than once:

| Header | Occurrences |
|---|---:|
| `Elapsed Time` | 2 |
| `Distance` | 2 |
| `Max Heart Rate` | 2 |
| `Relative Effort` | 2 |
| `Commute` | 2 |

Standard dictionary-based CSV loading is unsafe because duplicate headers overwrite or
reject fields. The adapter must:

1. Read the CSV positionally.
2. Validate the complete source header.
3. Assign stable internal names to duplicate columns.
4. Preserve the original column position in import metadata.
5. Normalize values only after source-column validation.

Cross-source calibration over 138 matched records found consistent scaling relationships:

- Strava elapsed-time values normalize to seconds.
- Garmin summary duration values normalize from milliseconds to seconds.
- The detailed Strava distance field normalizes to metres.
- Garmin summary distance values normalize from centimetres to metres.

These conversions must be implemented as explicit, tested source mappings rather than
inferred dynamically during every import.

## Deduplication evidence

Raw binary hashes cannot identify Garmin-Strava duplicates. No Strava FIT hash exactly
matched a Garmin FIT hash, even when both files represented the same activity. Providers can
rewrite FIT metadata or serialization while preserving activity semantics.

Cross-source deduplication therefore uses semantic evidence.

### Deduplication tiers

1. Within-source identity:
   - Source activity identifier
   - Source filename
   - Raw-file checksum
   - Import provenance

2. Strong cross-source match:
   - Compatible running classification
   - Start time within the strict tolerance
   - Compatible duration
   - Compatible distance
   - Unique candidate

3. Fuzzy candidate:
   - Wider start-time difference
   - Strong duration and distance agreement
   - Compatible sport
   - Indoor or GPS-missing context
   - Explicit confidence and review status

A checksum remains useful for idempotency within one source, but not as the only
cross-provider deduplication key.

No ambiguous running match was found in the inspected dataset.

## Field-level source precedence

For an overlapping running activity, canonical fields follow this order:

| Data category | Preferred source | Fallback |
|---|---|---|
| User-confirmed correction | User override | Provider data |
| Detailed recent trackpoints and sensors | Garmin raw FIT | Strava FIT.GZ |
| Recent activity summaries | Garmin summary | Strava summary |
| Historical activity summaries | Strava summary | Raw-file derivation |
| Historical route and elevation | Strava GPX or FIT | Summary fields |
| Missing Garmin raw activity | Strava FIT.GZ | Summary only |
| Provider-specific estimates | Original provider namespace | None |

Source precedence is field-level rather than row-level. A canonical activity may combine
Garmin sensor data, Strava historical metadata, and derived RunCoach metrics while retaining
complete provenance.

## Missing-data policy

Missing values are meaningful and must remain explicit.

- Historical GPX records legitimately lack heart rate and cadence.
- Indoor runs legitimately lack GPS and elevation.
- The summary-only historical run has no trackpoints.
- Power, temperature, and respiration rate are unavailable across the inspected running FIT
  files.
- Vendor VO2max is absent for some recent runs.
- Algorithms must declare their required inputs and coverage.
- Dashboard comparisons must identify when population size changes because of missing
  sensors.
- ML features must include availability rules and must not turn historical missingness into
  false physiological signals.

## Implementation consequences

The ingestion architecture requires:

- A positional Strava CSV adapter
- A namespace-aware GPX adapter
- A Garmin FIT SDK adapter supporting FIT and FIT.GZ streams
- A Garmin summary JSON adapter
- Source-unit normalization
- File and record provenance
- Running-type normalization
- Summary-only activity support
- Transactional and idempotent imports
- Semantic cross-source deduplication
- Field-level source precedence
- Structured validation findings
- Coverage-aware downstream analytics

The official Garmin FIT SDK is used for FIT decoding because it understands the FIT profile,
validates CRC data, and exposes structured session, lap, and record messages.

## Privacy controls

- Raw archives and extracted files remain under ignored private directories.
- No raw route coordinates are committed.
- No private filenames or source identifiers are documented.
- Logs use import identifiers rather than activity names.
- Sanitized fixtures must alter timestamps, coordinates, names, and identifiers.
- Public and cloud demonstrations use synthetic or sanitized records only.
- Raw GPS data is not sent to an LLM by default.

## Limitations

- The audit covers one athlete and the currently available export versions.
- Provider schemas may evolve.
- Source classification can be wrong, as shown by the treadmill-to-walk discrepancy.
- Cross-source matching requires conservative tolerances and provenance.
- Historical activities have lower sensor coverage than recent activities.
- Field availability does not establish measurement accuracy.
- Garmin vendor metrics are useful comparison signals but are not independent ground truth.

## Accepted ingestion baseline

The ingestion milestone is accepted when it can:

1. Import the 130 canonical running activities without exposing private data.
2. Represent all 45 historical and 85 Garmin-era runs.
3. Parse FIT, FIT.GZ, GPX, JSON summaries, and the positional Strava CSV.
4. Preserve the one summary-only historical activity.
5. Recover the missing Garmin raw treadmill activity from Strava FIT.GZ.
6. Normalize source units explicitly.
7. Produce no ambiguous running duplicates.
8. Remain idempotent when the same exports are imported again.
9. Record source provenance and validation findings.
10. Exclude non-running activities from running analytics.

## Persistence validation

The reconciled summary dataset was persisted to local PostgreSQL on 2026-08-26.

| Measure | Result |
|---|---:|
| Canonical running activities | 130 |
| Total canonical distance | 1,376.08 km |
| Earliest activity date | 2024-05-21 |
| Latest activity date | 2026-08-23 |
| Strava source representations | 130 |
| Garmin source representations | 85 |
| Resolved source representations | 215 |
| Data-quality findings | 0 |

A second import of the same files accepted zero new files, classified both files as
duplicates, reused all 130 canonical activities, and created zero activities or source
representations. This verifies file-level and activity-level idempotency for the inspected
exports. It does not establish completeness beyond those exports or validate physiological
interpretation.