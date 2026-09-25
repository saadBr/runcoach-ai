# ADR-0003: Introduce Resumable Authenticated Multi-Athlete Strava Onboarding

## Status

Accepted incrementally; persistence foundation implemented

## Date

2026-09-07

## Decision owners

PaceCraft AI project team and data owner

## Context

The original MVP was authenticated by deployment and configured one athlete through an environment
variable. That proved the ingestion, analytical, prediction, planning, and coaching paths, but it
does not support a real athlete onboarding experience or safe cross-athlete research.

A plan requires historical evidence. Allowing an account to enter the normal dashboard without a
usable activity history would either produce unavailable outputs or encourage the system to invent
personalization. Signup must therefore require a Strava export ZIP and a race goal before coaching
is activated.

Large archives cannot be parsed reliably inside one account-creation transaction. Uploads can time
out, contain unsafe paths, exceed resource limits, or yield no eligible running history. The user
must be able to sign back in and retry without recreating their identity.

Collecting more athlete histories may support a future population model, but account creation is
not consent to research. Raw exports and identifiable records also must not become training data.

## Decision drivers

- Make the product useful immediately after signup rather than showing an empty dashboard.
- Preserve strict ownership boundaries between athletes.
- Recover safely from interrupted or invalid archive processing.
- Keep credentials separate from activity and physiological data.
- Retain the existing local single-athlete workflow while migration is in progress.
- Support voluntary cross-athlete research without making it a condition of coaching access.
- Keep raw Strava data outside model-training and language-model boundaries.

## Decision

Every login account maps one-to-one to an athlete domain identity. Authentication state is stored in
dedicated account and revocable-session tables rather than on the `athletes` row. Persisted sessions
contain only a hash of an opaque bearer token.

The signup interface requires:

- Display name.
- Normalized email login identifier and password.
- IANA timezone.
- Race distance, date, optional target time, and weekly availability.
- One Strava export ZIP.
- An optional, separately worded model-research consent decision.

The backend implements signup as a resumable state machine:

1. Create the account, athlete, onboarding row, and goal in a short transaction.
2. Stream the archive into restricted temporary storage with bounded size.
3. Validate archive structure, expansion size, entry count, and paths.
4. Import eligible Strava history through the existing provenance pipeline.
5. Calculate versioned analytics and performance evidence.
6. Generate and persist the initial plan.
7. Mark onboarding and the account ready only after all required evidence exists.

The interface presents these steps as one required signup journey, while the account remains
`pending_onboarding` until processing succeeds. A failed or interrupted job can be resumed. The
ordinary dashboard, predictions, plan, and coach remain inaccessible before `ready`.

Every private API request will derive `athlete_id` from the authenticated session. Client-supplied
athlete identifiers are not authorization evidence.

Research consent is append-only and versioned. Only athletes whose latest decision is `granted`
may contribute pseudonymized derived features and verified outcomes. Withdrawing consent excludes
future research exports without disabling the athlete's account or personal coaching.

## Implemented identity and session boundary

- `user_accounts`: unique login identity, athlete mapping, password-hash field, and account status.
- `auth_sessions`: revocable opaque session hashes and expiration metadata.
- `athlete_onboarding`: required Strava import, goal, plan, progress, and sanitized failure state.
- `research_consents`: append-only granted or withdrawn decisions tied to a policy version.
- `runcoach.cli.bootstrap_account`: an interactive, idempotent compatibility command that claims
  the configured existing athlete only after verifying persisted Strava, goal, and plan evidence.
- `runcoach.db.identity.AuthenticationService`: normalized credential verification, opaque session
  issuance, hash-only persistence, expiry validation, and revocation.
- `/api/v1/auth/login`, `/api/v1/auth/me`, and `/api/v1/auth/logout`: sanitized authentication
  contracts used by the Streamlit login gate.
- Private analytics and coaching endpoints derive `athlete_id` from the authenticated session;
  the dashboard sends no athlete identifier.

New-athlete registration and safe Strava ZIP ingestion remain separate verified checkpoints. This
local authentication implementation is not claimed as production-ready until HTTPS, rate limiting,
credential recovery, and a deployment security review are complete.

## Security and privacy rules

- Plaintext passwords and bearer tokens are never persisted or logged.
- Email addresses are private identifiers and never enter model features or LLM context.
- Archive filenames, entries, raw bytes, and exact paths are excluded from public responses.
- ZIP handling must prevent path traversal, excessive expansion, excessive entry counts, encrypted
  entries, unsupported formats, and duplicate submission side effects.
- Temporary raw content is deleted after the import reaches a terminal state unless a documented
  private recovery policy retains the original export.
- Cross-athlete queries require explicit research-service boundaries and current consent.
- Production activation requires security review, rate limiting, credential recovery, and HTTPS.

## Options considered

### Keep deployment-level single-athlete identity

Simpler and retained as a compatibility mode, but it cannot support athlete signup, isolated
histories, or population-level evaluation.

### Require the archive and finish all parsing in one HTTP transaction

Not selected. It appears atomic to the UI but is fragile for large exports and prevents reliable
retry or progress reporting.

### Allow signup without history and create a generic plan

Not selected. A generic plan contradicts the evidence-grounded product claim and can hide
insufficient data.

### Treat terms acceptance as automatic model-research consent

Not selected. Coaching access and secondary research have different purposes and must remain
independent choices.

### Use a managed identity provider immediately

Deferred until the public deployment target is selected. It can reduce credential-handling risk,
but adds an external dependency and does not remove the need for local athlete ownership and
onboarding state.

## Consequences

### Positive

- Each athlete receives an evidence-backed plan only after usable history exists.
- Interrupted onboarding is recoverable and observable.
- Account security is isolated from analytical domain models.
- Consent decisions are auditable and reversible.
- Future population experiments can use athlete-level holdouts and chronological splits.

### Negative

- Authentication, authorization, archive security, account recovery, and deletion increase scope.
- Existing services that read `RUNCOACH_ATHLETE_ID` require a controlled migration to session
  ownership.
- Multi-athlete correctness requires auditing every import and analytical query for tenant scope.
- Public private-data hosting creates operational and governance duties absent from the local MVP.

## Verification

- Schema tests verify one account per athlete and one unique normalized email.
- Session schema tests verify that no recoverable token column exists.
- Onboarding constraints prevent `ready` without import, goal, and plan evidence.
- Consent schema tests verify append-only decision history.
- Alembic upgrade, downgrade ordering, and schema-drift checks cover the new tables.
- Later service tests must prove invalid login behavior, session revocation, cross-athlete denial,
  ZIP safety, resumable failure, idempotent retry, and onboarding activation gates.

## Revisit conditions

Review this decision before:

- Enabling public signup.
- Selecting or replacing the identity provider.
- Retaining raw archives in object storage.
- Exporting the first cross-athlete research dataset.
- Adding organization, coach, or administrator roles.
- Changing consent purpose or policy wording.

## Related documents

- `docs/requirements.md`
- `docs/architecture.md`
- `docs/data-model.md`
- `docs/adr/0002-personal-data-handling.md`
- `docs/testing-strategy.md`
- `docs/deployment.md`
