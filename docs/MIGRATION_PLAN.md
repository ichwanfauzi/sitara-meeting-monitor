# SITARA — Migration Plan from Prototype to Modular Starter

## Decision
Use the clean engineering starter as the active application foundation. Keep the legacy prototype as a reference for existing business concepts and UI behavior; do not copy it wholesale because its SQLite-era models and auth assumptions do not match the PostgreSQL target design.

## Legacy concepts identified
- User and role field
- Meeting
- MeetingNote
- Decision
- DecisionBrief
- ActionItem
- AuditLog (present in legacy prototype; needs a dedicated target implementation)

## Target modular layout
```text
backend/app/
  api/routes/       # HTTP endpoints only
  core/             # settings, security, permissions
  db/               # session, base, migrations integration
  models/           # SQLAlchemy models
  schemas/          # Pydantic request/response contracts
  services/         # business workflows
  repositories/     # persistence queries where useful
  tests/            # API/service/model tests
frontend/src/
  app/              # router and app shell
  components/       # shared UI
  features/         # meetings, minutes, decisions, action-items, briefs
  lib/              # API client and utilities
  types/            # shared frontend types
```

## Mapping guide
| Legacy prototype | Target design direction | Notes |
|---|---|---|
| `User.role` | `users` + `roles` + `user_roles` | Enforce permission checks server-side; do not trust role sent by frontend. |
| `Meeting` | `meetings`, `meeting_participants`, `agendas` | Preserve lifecycle and designated notetaker rules. |
| `MeetingNote` | `discussion_notes` or approved minutes tables | Keep one source of truth; clarify edit/version rules. |
| `Decision` | `decisions` | Decisions may or may not create action items. |
| `DecisionBrief` | `decision_briefs` linked to meeting and decisions | Treat as generated/reviewable document, not duplicate free text. |
| `ActionItem` | `action_items`, assignments, progress updates | Keep official status controlled by Secretariat per ADR. |
| `AuditLog` | `audit_logs` | Append-only history, record actor and entity; avoid sensitive payloads. |

## Required migration gates
1. Validate business rules and role matrix with the owner.
2. Review `sitara_schema_v1_draft.sql`; decide UUID strategy, constraints, and indexes.
3. Implement Alembic initial migration; do not execute against production during development setup.
4. Add negative authorization tests before exposing endpoints.
5. Port one vertical slice at a time: meetings -> live notes -> decisions -> action items -> brief -> progress/approval -> documents/notifications/audit.
6. Rebuild UI feature-by-feature; verify API contracts and responsive/accessibility behavior.
7. Only then plan import of existing SQLite/demo data, with backup and dry-run validation.

## Explicitly not done in this workspace
- No prototype frontend pages have been copied because the uploaded ZIP did not contain those prototype source files; the current `SITARA` GitHub repository is a separate source and must be imported selectively in a later verified step.
- No production SQLAlchemy models are registered from `legacy_prototype.py`.
- Authentication/session foundations and the initial identity migration exist; account provisioning and complete RBAC are still missing.
- Rapim metadata models/API cover meetings, agendas, and participants with role- and object-scoped access. Minutes revisions are append-only; version 2 stores complete discussion/decision snapshots under agendas. Review attestations remain bound to an exact revision, and the editor uses the existing revision API without real-time collaboration.
- Alembic migrations `0002_meetings_agendas`, `0003_workflow_rate_limit`, `0004_minutes_review`, `0005_versioned_minutes`, `0006_structured_minutes`, `0007_decision_brief`, and `0008_organization_scope` add meeting data, transition/rate-limit records, review attestations, versioned minutes, agenda-structured snapshots, immutable Decision Brief drafts, and empty organization-scope tables. Production migration rollout has not been verified.
- `0008_organization_scope` adds units, effective-dated user memberships, and effective-dated reporting lines. It deliberately inserts no organization data. Provisioning requires an approved unit chart and employee roster; a later controlled workflow must detect overlapping effective periods, validate hierarchy cycles, and audit changes. Downgrade refuses while any organization rows exist.
- The ORM identity metadata now matches the existing `0001_identity_sessions` email uniqueness constraint and session-user index; this alignment does not change the database schema.
- Dashboard metrics remain labeled synthetic data and are not connected to the API.

### Meeting lifecycle and login protection baseline

- `POST /api/v1/meetings/{meeting_id}/minutes-revisions` retains the legacy request `{ "content": string, "base_revision_id": UUID | null }` as version 1 and also accepts `{ "format_version": 2, "content": null, "base_revision_id": UUID | null, "discussions": [...] }`. Each discussion has an `agenda_id`, optional `subject`, nonblank `content`, and nested decisions with text and optional output, date, and action-item marker. PIC assignment, task creation, and task workflow are not implemented in this phase; unexpected assignment fields return `422`. The endpoint requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, and the designated notetaker. It appends one complete snapshot and returns `201`. Version 1 text and version 2 aggregate text are capped at 1,000,000 characters; structured field lengths and list counts are bounded. A stale base returns `409`; invalid input or out-of-meeting references return `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-revisions` returns ordered history to authorized Secretariat or leadership users in meeting scope. Responses add `format_version` and `discussions`; legacy revisions retain their original `content` and have an empty discussion list, while version 2 has `content: null` and full nested data. PIC and Super Admin are denied even when they also hold another role. Unknown or inaccessible meetings return `404`.
- `POST /api/v1/meetings/{meeting_id}/minutes-reviews` accepts `{ "minutes_revision_id": UUID, "result": "VALID" | "INVALID", "review_note"?: string }`, requires an authenticated session, CSRF header, an accessible meeting in `LIVE`, the currently active revision, and the `SEKRETARIAT` role without `SUPER_ADMIN`. It returns `201` with the meeting, revision, reviewer, per-meeting review number, result, timestamp, and optional note. A stale or wrong-meeting revision returns `409`; invalid input returns `422`.
- `GET /api/v1/meetings/{meeting_id}/minutes-reviews` returns the ordered review history to an authenticated, authorized Secretariat user. Inaccessible meetings return `404`, and visible meetings return `403` to roles without review authority.
- `POST /api/v1/meetings/{meeting_id}/transition` accepts `{ "to_status": "LIVE" | "FINAL" | "ARCHIVED" }`, requires the session cookie, CSRF header, and Secretariat role, and returns the updated meeting. PIC, leaders, and Super Admin cannot transition meetings; Super Admin remains excluded even if another role is also attached.
- Allowed transitions are `DRAFT → LIVE`, `LIVE → FINAL` after the latest review is `VALID`, and `FINAL → ARCHIVED`. The service locks the meeting row and commits the status change with a `meeting_status_events` row containing actor, previous status, target status, and time. Repeated, illegal, or unreviewed finalizations return `409` without changing status or writing an event.
- Revisions are full append-only snapshots. Version 1 stores the exact submitted text; version 2 stores no duplicate text and owns child discussion/decision rows. The active revision is the greatest per-meeting sequence; no separate hash or mutable active flag is maintained. Composite foreign keys keep discussions on agendas within the same meeting and decisions within the same revision. The service validates all child references, then commits root and children atomically. Migration triggers reject update/delete; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. These guards do not protect against a database owner or superuser altering the triggers; production should use a migration owner separate from a runtime role without DDL privileges. New writes must include the active `base_revision_id` (or `null` for the first revision), and service row locks serialize revision writes, review writes, and lifecycle transitions. A mismatch returns `409` rather than silently accepting a stale edit.
- `minutes_reviews.minutes_revision_id` references a revision with a composite `(meeting_id, minutes_revision_id)` foreign key, so reviews cannot point across meetings. Migration `0004` reviews are preserved with a null revision reference; they remain historical records but cannot authorize finalization. Every finalization rechecks that the latest review is `VALID` and names the active revision inside the locked transaction. A newer revision makes earlier reviews stale without changing them.
- Login reserves every request, including successful and failed attempts, in a fixed-window bucket keyed by HMAC of the normalized login identity and `request.client.host`. Default configuration is 10 attempts per 300 seconds and a 2-second PostgreSQL statement timeout. These are adjustable starting values, not universal security limits.
- Configure `LOGIN_RATE_LIMIT_HMAC_KEY` with a private random value of at least 32 characters. `429` responses include `Retry-After`; a missing key or limiter database failure returns `503` before password authentication. The limiter reads `request.client.host` and does not inspect forwarding headers. The documented local Uvicorn command disables proxy-header rewriting; behind a deployment proxy, enable it only with an explicit trusted proxy allowlist.
- The limiter stores only a keyed digest, counter, and window timestamps. Expired rows are deleted opportunistically on login and can be cleaned when idle from the repository root with `$env:PYTHONPATH = "backend"` followed by `python -m app.maintenance` in PowerShell. Schedule that command against the intended application database; it requires PostgreSQL and deletes only expired buckets.
- **Historical baseline (2026-10-15):** At that time `0005_versioned_minutes` was head. Upgrade/downgrade/re-upgrade and `alembic check` passed on a disposable PostgreSQL 16 tmpfs container; 9 PostgreSQL concurrency/constraint tests passed. Production rollout remains unverified.
- **Rollback warning:** downgrading `0004_minutes_review` drops the `minutes_reviews` table and all review attestations in it. The downgrade was exercised only on the disposable test database; do not use it after reviews contain records that must be retained. For deployed data, prefer a reviewed forward migration or a verified backup-and-restore plan.
- **Versioned-minutes rollback warning:** downgrading `0005_versioned_minutes` removes every revision and content snapshot and drops review-to-revision associations. Review rows from `0004` remain unattached after a direct downgrade to `0004`; any further downgrade through `0004` removes those review rows as well. Do not downgrade once the data is in use; use a reviewed forward migration or verified backup/restore.
- **Structured-minutes rollback warning:** `0006_structured_minutes` refuses downgrade if any `format_version=2` revision exists, so it will not silently drop structured discussions or decisions. With only version 1 rows it restores the version 1 schema while preserving legacy text and review bindings. Deployed rollback still requires a reviewed backup/restore or forward recovery plan.
- **Decision Brief rollback warning:** `0007_decision_brief` adds the composite source-decision constraint and two append-only tables. It refuses downgrade while any brief version exists. New source decisions must belong to the same meeting and exact source revision; `is_stale` is derived at read time by comparing the source revision ID to the active minutes revision. Test the migration and downgrade only in a disposable database.
- **Organization scope rollback warning:** `0008_organization_scope` creates empty organization tables without seeds. Its downgrade refuses while any unit, membership, or reporting line exists. Do not delete provisioned organization records merely to downgrade; use a reviewed forward recovery plan.

## Rapim metadata API contract

The current backend contract covers meeting metadata and the initial lifecycle transition:

| Method and path | Access and behavior |
|---|---|
| `GET /api/v1/meetings` | Authenticated Sekretariat sees all meetings; Rektor/Warek see meetings where they are creator, chairperson, notetaker, or participant. Supports bounded `limit` and non-negative `offset`. |
| `POST /api/v1/meetings` | Sekretariat, Rektor, and Warek may create a meeting. The server sets status to `DRAFT`; request bodies cannot override status. |
| `GET /api/v1/meetings/{meeting_id}` | Same object scope as the list; inaccessible or unknown meetings return `404`. |
| `POST /api/v1/meetings/{meeting_id}/agendas` | Sekretariat may manage any draft; Rektor/Warek may manage a draft they created. Agenda number is unique within its meeting. |
| `POST /api/v1/meetings/{meeting_id}/participants` | Same draft-management scope; each user can be added once per meeting. |
| `GET /api/v1/meetings/{meeting_id}/minutes-revisions` | Secretariat and authorized leadership within meeting scope; returns ordered text or structured revisions. PIC and Super Admin are denied. |
| `POST /api/v1/meetings/{meeting_id}/minutes-revisions` | Designated notetaker only, with session and CSRF, while `LIVE`; appends a revision only when `base_revision_id` matches the active revision. |
| `GET /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; returns the review history for an accessible meeting. |
| `POST /api/v1/meetings/{meeting_id}/minutes-reviews` | Secretariat only, excluding Super Admin; accessible meetings must be `LIVE`, and `minutes_revision_id` must identify the active revision. Appends an attributable review attestation. |
| `POST /api/v1/meetings/{meeting_id}/transition` | Secretariat only. `DRAFT → LIVE`, `LIVE → FINAL` with latest valid review, and `FINAL → ARCHIVED` are allowed; other transitions or missing/invalid review return `409`. |

All write routes require the authenticated session cookie and `X-CSRF-Token` matching the `sitara_csrf` cookie. PIC has no meeting metadata access and cannot read minutes content. Super Admin is denied even if another role is also attached, preserving its separation from operational Sekretariat access. Meeting responses include lifecycle status (`DRAFT`, `LIVE`, `FINAL`, `ARCHIVED`). Revision history is append-only and ordered by revision number. Review history is also ordered by review number; finalization requires its latest result to be `VALID` and its revision ID to equal the current highest revision. A newer revision invalidates prior reviews. The same Secretariat user may review and finalize. Only Secretariat may start (`DRAFT → LIVE`) or archive (`FINAL → ARCHIVED`) a meeting.

The data path is `Meeting 1:N Agenda`, `Meeting 1:N MinutesRevision`, `MinutesRevision 1:N MinutesDiscussion`, `Agenda 1:N MinutesDiscussion`, `MinutesDiscussion 1:N MinutesDecision`, `MinutesRevision 1:N MinutesReview`, `Meeting 1:N DecisionBriefVersion`, and `DecisionBriefVersion 1:N DecisionBriefDecision`. Brief entries reference the exact source decision in the brief's source revision; their editorial priority and notes do not duplicate decision text. Action items remain a future module and must reference decisions through a non-unique foreign key because one decision may yield zero or multiple tasks.

## Stage 7.3 — Database migration assessment and recovery plan

This is an assessment only. The main database was not migrated, downgraded,
reset, or reseeded. The API and evidence scanner were not started.

### Main database and schema comparison

The current main PostgreSQL container is healthy on `postgres:16-alpine` and
still uses the existing `sitara_merged_workspace_sitara_postgres_data` volume.
Its `alembic_version` is `0001_identity_sessions`. The five public tables are
`alembic_version`, `roles`, `users`, `user_roles`, and `user_sessions`.
`roles` contains the five seeded role rows; `users`, `user_roles`, and
`user_sessions` each contain zero rows.

The live `0001` columns, primary/unique/foreign-key constraints, and indexes
match the initial migration: unique role code and email, composite
`user_roles` primary key with user/role foreign keys, unique session token
hash, and the user-session lookup index. The `created_at` columns retain their
`CURRENT_TIMESTAMP` server defaults. The other tables required by the current
repository are absent because revisions `0002` through `0011` have not been
applied; this is the expected migration gap, not an unexplained extra-table
drift.

On the restored disposable copy, all migrations reached
`0011_evidence_scan_quarantine`; the resulting schema had 26 public base
tables including `alembic_version`. `alembic check` reported “No new upgrade
operations detected,” so current SQLAlchemy metadata matches the migration
head in that rehearsal. No live schema comparison against `0011` was possible
or attempted on the main database.

### Migration chain and impact

The linear chain is:
`0001_identity_sessions` → `0002_meetings_agendas` →
`0003_workflow_rate_limit` → `0004_minutes_review` →
`0005_versioned_minutes` → `0006_structured_minutes` →
`0007_decision_brief` → `0008_organization_scope` →
`0009_action_items` → `0010_action_item_evidence` →
`0011_evidence_scan_quarantine`.

| Revision | Upgrade effects | Data, rollback, and operational risk |
|---|---|---|
| `0001_identity_sessions` (base) | Creates `roles`, `users`, `user_roles`, and `user_sessions`; adds PKs, unique role/email/token constraints, FKs, and the session user index; inserts five role rows. | Downgrade drops identity and session data. |
| `0002_meetings_agendas` ← `0001` | Creates `meetings`, `meeting_participants`, and `agendas`; adds meeting lifecycle/time checks, FKs, unique meeting/agenda numbers, and lookup indexes. | No backfill. Downgrade drops meeting, participant, and agenda data. |
| `0003_workflow_rate_limit` ← `0002` | Creates `meeting_status_events` and `login_rate_limit_buckets`, with transition/window checks, FKs, and indexes. | No backfill. Downgrade removes status-event and limiter history. |
| `0004_minutes_review` ← `0003` | Creates attributable `minutes_reviews`, its result/sequence checks, FKs, and per-meeting review-number uniqueness. | No backfill. Downgrade deletes review attestations. |
| `0005_versioned_minutes` ← `0004` | Creates append-only `minutes_revisions`; adds nullable `minutes_revision_id`, same-meeting FK, and index to reviews. | Existing reviews are preserved but remain unbound. Downgrade drops revisions and the association; further downgrade through `0004` deletes reviews. |
| `0006_structured_minutes` ← `0005` | Adds `format_version` (default 1), makes revision content nullable, replaces content checks, adds agenda uniqueness, and creates `minutes_discussions`/`minutes_decisions` with same-meeting/revision FKs and append-only guards. | Existing text remains format 1; there is no content-to-agenda conversion. Downgrade refuses while format-2 snapshots exist. DDL alters existing tables and adds constraints. |
| `0007_decision_brief` ← `0006` | Adds exact-source uniqueness and creates append-only `decision_brief_versions` and `decision_brief_decisions`, with revision-bound composite FKs and indexes. | No backfill. Downgrade refuses while brief versions exist. |
| `0008_organization_scope` ← `0007` | Creates empty `organization_units`, `user_unit_memberships`, and `reporting_lines`; adds effective-period/self-reference checks, FKs, uniqueness, and period indexes. | No organization data is seeded. Downgrade refuses while any of these tables has rows. |
| `0009_action_items` ← `0008` | Creates `action_items`, `assignments`, `progress_updates`, `completion_verifications`, and `status_histories`; adds status/provenance checks, composite FKs, partial unique assignment indexes, and integrity/append-only triggers. | No backfill. Downgrade refuses while task or history rows exist; it would otherwise remove all five tables. |
| `0010_action_item_evidence` ← `0009` | Makes progress assignment nullable, adds `submitted_as` default `PIC`, replaces assignment constraints/guards, and creates `action_item_evidence` with file/link metadata, size/type/checksum checks, indexes, and evidence-limit/append-only guards. | Existing progress rows receive the `PIC` default. Downgrade refuses if evidence or leadership progress exists; it also removes the evidence table and the leadership-progress capability. |
| `0011_evidence_scan_quarantine` ← `0010` | Creates append-only `action_item_evidence_scans`, event/status/checksum constraints and guards; inserts a first `PENDING` event for every existing `FILE` evidence row. | This is the chain’s data backfill; work and transaction/WAL volume scale with the number of existing files. Downgrade refuses while scan history exists. |

Most revisions create new tables, but `0005`, `0006`, `0007`, and `0010`
also alter existing tables or add constraints/indexes. The migrations use
ordinary index creation rather than `CREATE INDEX CONCURRENTLY`; PostgreSQL
DDL and index operations can hold locks. Production-sized lock duration,
WAL growth, and migration downtime have not been measured. Rehearse with
representative data and schedule a write-quiesced maintenance window. Do not
use downgrade as the default recovery plan: several revisions intentionally
refuse to discard populated history, while earlier downgrades drop data.

### Backup and restore evidence

For this assessment, `pg_dump` produced a custom-format archive outside the
database volume in a temporary Windows directory restricted to the current
user. The archive was 8,204 bytes with SHA-256
`e16bb9e77f2f2dbf4231060722a283f6b6f1f14683ecbb8803711f427c875ccb`.
`pg_restore --list` validated its format. The archive was restored with
`pg_restore --exit-on-error --no-owner --no-acl` into a separate PostgreSQL 16
container whose data directory was tmpfs-only and which had no Docker volume
mount. The restored revision, five role rows, and empty identity-table counts
matched the source.

**Backup restore test: PASS for this temporary archive.** After restore, the
disposable database upgraded from `0001` to `0011`, `alembic check` found no
schema diff, downgraded to `0001`, and upgraded back to `0011`. The full
backend suite also passed against a separate restored/migrated disposable
database. The dump and both scratch databases were removed after verification.
There is **no retained operational backup** from this assessment, and an
encrypted/off-device backup was not tested; durable backup readiness therefore
remains **NOT VERIFIED**. The restore source had no evidence files, so the
`0011` positive-row `PENDING` backfill was not exercised by this rehearsal.

Before any approved main-database migration:

1. Quiesce writes and create a fresh custom-format `pg_dump` outside the
   database volume. Protect it with approved encryption and access controls;
   store a copy outside the host/account failure domain. Provision database
   roles separately through the approved secret process (a database dump is
   not a secret-management mechanism).
2. Record archive size and SHA-256, validate with `pg_restore --list`, then
   restore that exact archive to a newly named PostgreSQL 16 disposable
   instance. Compare revision, table/constraint/index inventory, and
   non-sensitive row counts; run the full migration rehearsal and relevant
   tests on the restored copy.
3. Coordinate a consistent private-file backup with the database snapshot.
   Evidence metadata and file bytes/checksums must restore together; the
   database-only restore test does not prove file recovery.
4. If a migration fails, stop API/worker writes, retain the original database
   and backup, inspect the last committed Alembic revision and PostgreSQL
   logs, and choose a reviewed forward fix or restore to a separate database
   for an approved cutover. Do not blindly retry, downgrade, or replace the
   original volume.

### Evidence storage readiness

Compose declares `sitara_action_item_evidence` at
`/var/lib/sitara/evidence`. The backend image creates that directory as
UID/GID `10001:10001` with mode `0700`; API mounts it read/write and the
single scanner mounts the same named volume read-only. The scanner reads and
hashes the bytes, then sends them to ClamAV through INSTREAM; ClamAV does not
need this volume mounted.

The main evidence volume is currently **absent**. Consequently volume
ownership, effective permissions, API write access, worker read access, and
post-restore file reconciliation are **NOT VERIFIED** for the main runtime.
Do not let an API `up` implicitly provision it before the database upgrade and
storage plan are approved. Provision only the exact named volume after a
preflight, verify owner/mode and API read-write/scanner read-only access using
synthetic evidence, and keep it outside any public/static web root.

### API/worker startup gate and next steps

- **PASS:** Main PostgreSQL is healthy on its existing PostgreSQL 16 image and
  original volume; the ClamAV service is healthy with its existing signature
  volume.
- **BLOCKED:** Main DB revision is `0001`; repository head is `0011`.
- **BLOCKED:** Main evidence volume is absent; storage ownership and access
  have not been verified.
- **NOT VERIFIED:** A durable encrypted backup plus restore of database and
  evidence files.
- **NOT VERIFIED:** Main API/worker connectivity, shared database/storage, and
  live status updates. Neither service was started.
- **REQUIRED:** Apply migrations only after explicit approval and a successful
  restore rehearsal from the exact retained backup. Keep migrations as an
  explicit one-off operation; API/worker startup must not run migrations
  automatically.
- **REQUIRED:** Confirm API and worker use the same database and evidence
  volume; API access is read/write, scanner access read-only; verify
  `clamav:3310` from the worker; keep exactly one scanner replica until
  atomic queue claiming/leases exist.

Recommended order after approval: retain and test the coordinated backup;
provision and permission-check the evidence volume; apply `alembic upgrade
head` as a separately monitored operation; verify revision/schema/read-only
counts; start the API and validate its database/ClamAV dependencies; then start
one worker and test a clearly identified synthetic evidence journey. Do not
run this sequence against the main environment until its operator authorizes
the migration and data-storage changes.

## Stage 7.4 — Backup readiness and evidence storage provisioning (2026-10-31)

This stage is assessment and rehearsal only. No main-database migration or
downgrade was run; the API and scanner worker were not started; the original
PostgreSQL and ClamAV volumes were not changed; and the main evidence volume
was not created. `.env` was not read or changed. The worktree remains
uncommitted.

### PostgreSQL backup and restore rehearsal

The main PostgreSQL service remained healthy on `postgres:16-alpine`, using
the original `sitara_merged_workspace_sitara_postgres_data` volume. Its
revision remains `0001_identity_sessions`; the five public tables are
`alembic_version`, `roles`, `user_roles`, `user_sessions`, and `users`.
The restored source counts matched: one Alembic revision row, five seeded
roles, and zero users, user-role assignments, or sessions.

A custom-format `pg_dump` was written as binary data to a temporary host
directory outside the database volume. The directory had Windows ACL
inheritance disabled and granted full access only to the current user. The
archive was 8,204 bytes, SHA-256
`8a27ccd53478b5cdbb23a8e9ea30b544392af273f20f9522bd771035125eaa18`, and
`pg_restore --list` exited successfully. It was restored with
`pg_restore --exit-on-error --no-owner --no-acl` into a separate PostgreSQL 16
container with a tmpfs-only data directory, no Docker volume mounts, and an
internal disposable network. The restored revision, all five table names,
columns, constraints, indexes, and row counts matched the source. The
normalized schema-inventory SHA-256 was
`406685d53eafafe1378002e991ac6df40064f405b988d410f061c836e8fb0b2b`.
The archive, disposable database, network, and temporary files were removed
after verification.

**Rehearsal result: PASS. Durable backup readiness: NOT VERIFIED.** This was a
temporary local backup and restore test, not a retained, encrypted,
off-device backup. No backup is currently available for the main database.
The SHA-256 and size above identify only this completed test archive; they do
not identify a retained operational backup.

Before any separately approved migration, the operator procedure is:

1. Select an approved host backup directory outside the PostgreSQL data
   volume. Restrict its ACL to the authorized backup identity (disable
   inherited broad access); use the approved encryption mechanism and copy the
   encrypted archive outside the host/account failure domain. The test's
   current-user-only temporary ACL is not a substitute for off-device storage.
2. Coordinate a maintenance window. Quiesce evidence uploads and scanner
   result writes while taking the database and evidence snapshots so their
   metadata and file bytes describe one recovery point.
3. Use `pg_dump --format=custom --no-owner --no-acl` against the intended
   database. When capturing output on Windows, use a binary-safe process
   stream rather than PowerShell text redirection. Do not put credentials in
   command output, scripts, or documentation.
4. Record the archive byte count and SHA-256. Validate the archive with
   `pg_restore --list`; encrypt it and transfer it using the approved
   off-device process.
5. Restore that exact archive into a uniquely named disposable PostgreSQL 16
   instance whose data directory is tmpfs or a uniquely labeled disposable
   volume and which has no published host port or main-volume mount. Verify
   the Alembic revision, tables, columns, constraints, indexes, and
   non-sensitive record counts before migration rehearsal or cutover.
6. If a migration fails, stop application writers, retain the original
   database and verified archive, and inspect the last committed revision and
   PostgreSQL logs. Use a reviewed forward fix or restore to a separate
   database for an explicitly approved cutover. Do not blindly retry,
   downgrade, reset, or replace the original volume.

The successful test proves this archive could be read and restored into the
disposable PostgreSQL 16 target. It does not prove a future archive, encryption,
off-device transfer, or production recovery objective; each must be checked
for the exact retained backup.

### Evidence backup strategy and storage verification

Compose declares the private evidence root at
`/var/lib/sitara/evidence`. The API mounts the evidence volume read/write; the
single scanner worker mounts the same volume read-only. The backend image runs
as UID/GID `10001:10001` and creates the storage root with mode `0700`. The
storage service uses opaque 32-character lowercase hexadecimal keys, rejects
path traversal and symbolic-link paths, writes files atomically with mode
`0600`, and records a SHA-256 digest. The scanner verifies the digest before
scanning. The API verifies it again when serving an authorized CLEAN file.

ClamAV does **not** mount the evidence volume. The worker reads the file from
its read-only mount and sends the bytes to the separate ClamAV daemon using
INSTREAM over internal TCP port 3310. Therefore the daemon requires no
filesystem permission on evidence storage.

A uniquely labeled disposable standard named-volume test used the backend
image at the actual Compose storage path. On first mount, the empty volume
inherited UID/GID `10001:10001` and root mode `0700`; the storage service wrote
a synthetic PDF as that non-root user with file mode `0600`. The file was
archived from a read-only source mount and restored to a second disposable
named volume. Its SHA-256 before and after restore matched
(`bc3edd07e0bf910ab86779f0004e91a6ab2f525208fa8810c964669280350416`).
The temporary 10,240-byte evidence archive had SHA-256
`45a7f19045eda6f1da30c1e80ee0fbcde726aea1a039ada831ed78ec8ffd3351`.
The restored root/file ownership and modes matched, and a scanner-style
read-only mount could read the file but could not write. The temporary archive,
containers, and both test volumes were removed after verification.

| Component/identity | Evidence-volume access | Required mode or path |
|---|---|---|
| API, UID/GID `10001:10001` | Read/write | Private root `0700`; files `0600` |
| Evidence scanner, UID/GID `10001:10001` | Read-only | Same Compose volume and storage path |
| ClamAV daemon, UID/GID `100:101` | No volume mount | Receives file bytes over internal ClamAV protocol |
| Authorized backup operator/helper | Read-only snapshot for backup; write only to a separate restore target | Preserve numeric ownership, modes, storage keys, and file bytes |

**Disposable permission and synthetic-file restore: PASS. Main evidence
storage readiness: NOT VERIFIED.** The expected main named volume
`sitara_merged_workspace_sitara_action_item_evidence` remains absent. No main
volume was created, mounted, or changed. The main database is still at
`0001_identity_sessions`, so its schema does not yet contain evidence
metadata or scan history; no actual `PENDING`, `CLEAN`, or `REJECTED` records
or files exist there to verify across restore. Preserving those states is a
database-and-file recovery requirement, not something this empty-source
rehearsal could prove.

For a coordinated recovery, preserve the PostgreSQL evidence rows and
append-only scan history together with the complete private file volume.
After restoring both, compare every stored file's size and SHA-256 with its
database metadata and confirm each latest scan status remains unchanged.
`PENDING` files must remain quarantined until the normal scanner records a
result; `REJECTED` files must remain inaccessible to download; do not
reconstruct or manually change scan status from filesystem contents.
Keep uploads and scanner result writes quiesced across the coordinated
snapshots. Encrypt the evidence archive and restrict its ACL independently
from the database archive. Never place either backup in the database volume
or a public/static web root.

### Safe provisioning procedure and startup gates

The disposable named-volume test verifies that the current backend image
initializes an empty volume with the expected owner and root mode. It does not
authorize provisioning the absent main evidence volume. After explicit
approval and a verified coordinated backup, provision only the exact
Compose-owned volume after confirming the resolved Compose project and volume
name. Before starting the API or worker, mount that volume in a uniquely
labeled disposable checker at `/var/lib/sitara/evidence`; verify root
ownership/mode and API-style non-root read/write, then verify the scanner
identity can read but cannot write. Use only a synthetic file and compare its
checksum. Do not publish the storage path or expose it through a web server.
Keep ClamAV unmounted from the evidence volume.

The API and worker may start only after all of the following are true:

- The main database is at the reviewed repository migration head
  `0011_evidence_scan_quarantine`; migration is a separately approved,
  monitored one-time operation, never an API/worker startup action.
- A fresh custom-format PostgreSQL archive is retained in approved encrypted
  storage outside the database volume and host failure domain; that exact
  archive passes `pg_restore --list` and a PostgreSQL 16 restore rehearsal.
- The evidence volume is explicitly provisioned and permission-checked, and
  a coordinated encrypted database/evidence restore has been verified.
- API and worker use the same database and evidence volume; API access is
  read/write and worker access is read-only.
- ClamAV is healthy and reachable as `clamav:3310` on the internal network.
- Exactly one scanner worker is configured; do not scale it until atomic
  queue claiming/leases and concurrency tests exist.
- The migration gap, backup/restore gates, volume identity, permissions, and
  rollback/forward-recovery plan have been reviewed by the operator.

**Stage 7.5: WAITING FOR APPROVAL.** Main database migration, main evidence
volume provisioning, and API/worker startup remain blocked. See
[`CLAMAV_EVIDENCE_SCANNING.md`](./CLAMAV_EVIDENCE_SCANNING.md) for the
operational evidence-scanning record.

## Stage 7.4.1 — Operational backup readiness (2026-10-31)

### Re-audit outcome

The Stage 7.4 archive and synthetic evidence tar were temporary rehearsal
artifacts and were removed after restore checks. Stage 7.4 did not establish
an operational backup directory, approved encryption/key custody, an
off-device destination, or a retention schedule.

The requested current host/Docker/storage audit could not be completed in this
execution: the sandbox refused to start its PowerShell process because access
to the local proxy is disabled. Drive inventory, available encryption
executables, current container state, and mounted volumes are therefore
**NOT VERIFIED in Stage 7.4.1**. The latest known state is the Stage 7.4
record above, not a fresh observation. No external storage was contacted and
no backup artifact was created or transferred.

| Readiness item | Status | Evidence |
|---|---|---|
| Approved destination outside the primary host/account failure domain | **BLOCKED** | No destination could be enumerated or independently verified in this run. A second directory or volume on the same host is not off-device. |
| Approved encryption tool and key custody | **BLOCKED / NOT VERIFIED** | The executable/key-management inventory could not run. No encryption operation was performed. |
| Restricted operational ACL and authorized backup identity | **NOT VERIFIED** | Stage 7.4 verified a temporary ACL for its local rehearsal only; that is not an operational backup destination. |
| Retention schedule and deletion authority | **BLOCKED** | No institution-approved retention policy was available. |
| Retained encrypted PostgreSQL backup | **NOT VERIFIED** | The Stage 7.4 test archive was deleted after disposable restore. |
| Coordinated database/evidence recovery point | **NOT VERIFIED** | Main DB remained at revision `0001_identity_sessions`, before evidence tables; main evidence volume was absent in Stage 7.4. |
| Current Docker and Git state | **NOT VERIFIED in Stage 7.4.1** | Shell preflight could not execute. Preserve the Stage 7.4 baseline as historical only. |

### Operational backup procedure (not yet enabled)

Do not run this procedure until an operator identifies and approves the
destination, encryption mechanism, key custodians, retention policy, and
maintenance window. The backup must never be treated as operational until the
exact encrypted files have been restored and verified from that destination.

1. **Destination and access control.** Select institution-approved storage
   outside the primary host and its failure domain (for example a separately
   administered backup host or approved object-storage account). Record its
   owner, region/failure domain, access policy, encryption policy, and restore
   contact without recording credentials. A different folder, partition,
   Docker volume, or attached disk on the same host does not meet this gate.
   Restrict both the local staging directory and remote object to named backup
   and restore identities; disable inherited broad ACLs, audit reads/writes,
   and prohibit public access.
2. **Encryption and key custody.** Use only an institution-approved,
   maintained file-encryption tool. Prefer recipient/public-key encryption or
   an approved managed key service so the decryption key is not stored beside
   the ciphertext or only on the source host. Restrict key access to named
   recovery custodians, document rotation/revocation and emergency access, and
   test decryption with the authorized restore identity. Do not write
   passphrases or private keys in scripts, shell history, logs, Compose files,
   the repository, or the backup destination. Tool selection and key custody
   are still **BLOCKED** pending operator approval.
3. **Quiesce and identify one recovery point.** Stop or pause all database
   writers that can change evidence metadata, including uploads and scanner
   result writes. Record a unique snapshot ID and UTC start/end times. Keep
   writers quiesced until both the logical database dump and evidence archive
   have been captured; otherwise the two artifacts may describe different
   states. Do not start the main API or worker to perform this assessment.
4. **Create a binary-safe PostgreSQL dump.** Run `pg_dump` in the intended
   PostgreSQL 16 context with custom format, `--no-owner`, and `--no-acl`.
   Capture stdout as bytes directly to a newly created restricted file stream
   (for example, copy the child process `StandardOutput.BaseStream` to a
   binary file); do not use PowerShell text redirection or decode/re-encode
   the archive. Keep stderr private and redact diagnostics before sharing.
   Never place the archive under the database data directory or a Docker
   volume used for PostgreSQL.
5. **Capture evidence from the same quiesced point.** Archive the complete
   private evidence root from a read-only mount while writes remain paused.
   Preserve relative storage keys, numeric UID/GID, file modes, timestamps
   where meaningful, and all file bytes. Do not omit files based on scan
   status: PENDING, CLEAN, and REJECTED file bytes and their metadata/history
   are all part of the recovery set. Do not follow symlinks or traverse
   outside the configured evidence root. Encrypt the evidence archive under
   the same approved key policy as the database archive.
6. **Create and verify a recovery manifest.** Store a non-secret manifest
   alongside the encrypted archives with the snapshot ID, capture times,
   database/evidence archive byte sizes and SHA-256 digests, database
   PostgreSQL major version and Alembic revision, non-sensitive schema/table
   counts, evidence metadata count and counts by latest scan status, file
   count, and tool/format versions. The manifest must not contain credentials,
   file contents, meeting content, or raw storage keys. Compute archive hashes
   before transfer and verify them again after transfer and before decryption.
7. **Validate, encrypt, transfer, and retain.** Run `pg_restore --list` on
   the plaintext custom-format dump before encrypting it, and verify the
   evidence archive can be listed without extracting it into a public path.
   Encrypt both archives, transfer only ciphertext and the non-sensitive
   manifest to the approved off-device destination, then verify remote byte
   sizes and SHA-256 against the manifest. Remove local plaintext staging
   copies only after remote integrity checks and policy-compliant handling;
   never claim secure erasure on storage that cannot prove it.
8. **Retention.** Apply only the institution-approved retention and legal
   hold policy. As a proposal for owner review—not an approved schedule—retain
   14 daily, 8 weekly, and 12 monthly recovery points, with an explicit
   deletion/hold audit. Until a schedule and deletion authority are approved,
   do not automate pruning or delete any operational backup.
9. **Restore the exact remote backup.** Fetch the selected encrypted set from
   the off-device destination, verify ciphertext hashes, decrypt using the
   authorized recovery identity, and verify plaintext hashes. Restore the
   database archive into an isolated PostgreSQL 16 disposable target and the
   evidence archive into a separate uniquely labeled disposable volume. Use
   no primary volumes, no production network access, and no published host
   ports. Keep the source backup immutable.
10. **Prove one recovery point.** Compare the restored Alembic revision,
    schema, and non-sensitive database counts to the manifest. Verify every
    FILE evidence metadata row has exactly one corresponding regular file;
    verify file size and SHA-256 against the database metadata; identify and
    report any orphan file rather than silently deleting it. Verify the
    latest status and scan history counts for PENDING, CLEAN, and REJECTED
    match the manifest. Confirm PENDING remains quarantined, REJECTED remains
    undownloadable, and CLEAN remains associated with the same digest and
    scanner result. Only after these checks may the backup be marked
    restore-tested.

The database and evidence snapshots are consistent only if writers remain
quiesced across both captures. A manifest and matching archive hashes prove
artifact identity/integrity; they do not alone prove application-level
consistency. Restore validation must check the cross-reference and digest
invariants above.

### Stage 7.4.1 decision

**Stage 7.4.1 readiness: BLOCKED.** The required encrypted copy outside the
primary host failure domain does not exist as verified evidence in this
workspace, and no restore rehearsal was performed against such a copy. The
Stage 7.4 local unencrypted rehearsal remains useful only as a disposable
format/restore test; it does not satisfy this stage's operational readiness
criterion.

No evidence source data was available for a combined recovery-point rehearsal
in Stage 7.4: the main database was still at `0001_identity_sessions` and the
main evidence volume was absent. The isolated database and synthetic-volume
tests from Stage 7.4 were separate tests, not one coordinated DB-plus-files
restore. Preservation of real PENDING/CLEAN/REJECTED metadata and file
checksums is therefore **NOT VERIFIED**.

Do not proceed to Stage 7.5. Main migration, main evidence-volume
provisioning, API/worker startup, and any off-device transfer remain
**WAITING FOR APPROVAL** and must first pass the gates in this plan.

## Stage 7.4.12 — SITARA backup architecture and recovery specification

**Status: SPECIFICATION COMPLETED; implementation and operational readiness
remain BLOCKED.** The current media priority is an external HDD for an
encrypted offline copy; campus Microsoft 365 OneDrive is a fallback/last
resort. A dedicated SITARA SharePoint document library is not available, and
IT has not provisioned a Microsoft Entra ID application for Microsoft Graph.
If OneDrive is later approved for use, the designated operator manually
uploads only already-encrypted files to an access-restricted campus OneDrive
folder; no Graph automation is assumed. The future VPS is the production
source, but is not yet available. Neither the HDD nor OneDrive destination,
production policy, key process, or operational backup has been verified.
Do not create a backup, transfer data, or change the main PostgreSQL service
under this specification.

### Operating model and scope

- **Local development:** use synthetic or explicitly approved development
  data. The external HDD is the planned priority medium for encrypted recovery
  packages. After copy and read-back verification, safely eject and disconnect
  it; a connected HDD is not offline and a separate device is not necessarily
  in a separate physical-site failure domain. Device availability, custody,
  capacity, location, and production suitability remain unverified.
- **OneDrive fallback:** campus Microsoft 365 OneDrive may be considered only
  as a fallback/last resort after IT and policy approval. A restricted folder
  can be configured, but the effective access policy, retention, capacity,
  recovery behavior, audit coverage, and failure-domain separation are
  unknown. SharePoint Document Library dedicated to SITARA is unavailable.
  Microsoft Graph automation is not available because IT has not provided an
  Entra ID application. If approved, a designated operator manually uploads
  ciphertext only after encryption, then verifies the remote files using an
  approved read-back procedure. Do not sync or upload plaintext staging data.
- **Production VPS (future):** treat the VPS as the source, not as the only
  backup destination. Create encrypted recovery packages on the VPS using
  restricted temporary staging, copy the verified ciphertext to the priority
  HDD, and consider the campus OneDrive fallback only under the approval and
  manual-upload conditions above. The HDD must be physically removed from the
  VPS host; a same-host disk or directory is not off-device. Whether the HDD
  is stored at a sufficiently separate site and whether OneDrive provides an
  independent failure domain must be established by IT.
- This is a logical backup specification, not a claim that backup jobs,
  scheduler, encryption, key management, monitoring, or cloud integration
  exist in the repository. No backup script or dependency is introduced here.

### PostgreSQL backup and validation

1. Select a unique recovery-point ID before capture, for example
   `sitara-prod-<UTC timestamp>-<UUID>`. Record the environment, UTC capture
   start/end, application release/commit, PostgreSQL server major version,
   client tool version, and Alembic revision without recording connection
   strings or credentials.
2. Quiesce application writes that can affect the recovery point, including
   evidence uploads and scanner result writes; wait for in-flight transactions
   to finish. A `pg_dump` snapshot is internally consistent, but does not by
   itself synchronize the separate evidence filesystem.
3. Use a PostgreSQL 16 `pg_dump` client for the current PostgreSQL 16 database,
   with custom format and `--no-owner --no-acl`. Write to a newly created
   restricted file using the tool's binary output (`--file` or a binary
   stream); do not use PowerShell text redirection, decode/re-encode the
   archive, or place plaintext under the database data directory or a Docker
   database volume.
4. Require a zero exit code, non-zero file size, SHA-256, and successful
   `pg_restore --list` before encryption. On any failure, mark the run
   **FAILED**, preserve the previous known-good recovery points, do not upload
   partial output as complete, and retain/delete plaintext staging only under
   the approved incident and retention procedure.
5. Restore only to a disposable PostgreSQL target, initially matching the
   source major version. Use `pg_restore --exit-on-error` and independently
   provision required database roles and grants through the approved
   credential/secret process; `--no-owner --no-acl` intentionally avoids
   embedding host-specific ownership/ACLs. Do not include password hashes,
   connection strings, or secret-bearing global-role dumps in the package.
6. PostgreSQL major-version upgrades are a separate change. Use a compatible
   `pg_dump` client (never older than the source server major) and rehearse
   restore into the intended target major before any production upgrade.

### Evidence backup and recovery-point consistency

The current implementation distinguishes `FILE` evidence from `LINK`
evidence. File metadata includes an opaque 32-character hexadecimal
`storage_key`, original filename, content type, size, SHA-256, uploader, and
creation time. The key is resolved only within the configured private storage
root. The storage helper rejects invalid keys, symlink paths/files, and
non-regular files; files are written atomically with private directory/file
permissions. Do not expose storage keys in a backup manifest.

`action_item_evidence_scans` records append-only scan events. The latest
`PENDING`, `CLEAN`, or `REJECTED` state is derived from that history. Downloads
are allowed only when the latest result is `CLEAN`, its scanned digest equals
the evidence SHA-256, and the actual file size and digest still match.
Therefore:

- Capture every FILE's bytes and all database evidence/scan history, without
  filtering by status. `PENDING` remains quarantined; `REJECTED` remains
  undownloadable; do not infer, rewrite, or promote a status during backup or
  restore. A restored `CLEAN` item remains usable only after its file digest
  and latest scan record are verified.
- `LINK` entries contain external URLs, not locally stored file bytes. The
  backup preserves their database metadata only; availability and retention of
  linked external content are outside this backup package and must be governed
  separately.
- Keep upload and scanner-result writers quiesced through both the database
  dump and evidence capture. Capture the evidence root from a read-only mount
  or equivalent snapshot. Archive regular files only, preserve their opaque
  keys and required numeric ownership/modes, reject symlinks, and never
  traverse outside the configured root.
- During restore rehearsal, map each FILE metadata row to exactly one regular
  file. Compare file size and SHA-256 to metadata and compare every CLEAN
  scan's `scanned_sha256` to the metadata digest. Report missing files,
  orphans, duplicate keys, invalid paths, and mismatches; do not auto-delete,
  repair, or mark records CLEAN.

The latest environment audit found the main database at
`0001_identity_sessions`, without evidence metadata or scan-history tables;
the main evidence volume, API, and scanner worker were absent. This is a
current readiness limitation: the proposed joint database/evidence recovery
point cannot yet be produced or tested from main evidence data. Earlier
database and synthetic-volume rehearsals were separate disposable tests, not
an operational joint recovery point.

### Recovery package and manifest

Use one immutable package directory per recovery point. A proposed layout is:

```text
sitara-backups/<environment>/<recovery-point-id>/
  database.dump.age
  evidence.tar.age
  manifest.json.age
  ciphertext-sha256.txt
```

`database.dump.age`, `evidence.tar.age`, and `manifest.json.age` are encrypted
artifacts. The inner manifest is encrypted because even aggregate counts,
schema revision, and capture details may be operationally sensitive. It
records:

- recovery-point ID, environment, UTC capture window, application release or
  commit, PostgreSQL server/client versions, Alembic revision, and archive
  format/tool versions;
- plaintext archive sizes and SHA-256 digests, database schema/table counts,
  evidence FILE count and counts by latest scan status, and validation
  outcomes;
- quiesce confirmation and any limitations, including whether the evidence
  root was absent or contained LINK-only metadata.

The outer `ciphertext-sha256.txt` contains only recovery-point ID, encrypted
artifact names, byte sizes, and ciphertext SHA-256 values so copies can be
checked before decryption. It contains no secrets, evidence content, raw
storage keys, URLs, credentials, or meeting data. Do not treat checksums alone
as authenticity if an attacker can replace both artifacts and checksum file;
use destination access/audit controls and an institution-approved signature
or immutable-object mechanism if available.

### Encryption and key custody

Encrypt each artifact on the source side **before** it is written to the
external HDD or uploaded to OneDrive. Proposed method for evaluation:
recipient-based `age` encryption for the database archive, evidence archive,
and protected manifest. The backup operator encrypts to an institution-
approved public recipient; the corresponding private decryption identity is
held separately under a formally appointed recovery key custodian. `age` is a
proposal, not an approved policy, installed dependency, or implemented tool;
the institution may select another maintained file-encryption mechanism
provided it supports offline recovery and passes the same tests.

The Director approves the encryption/key policy and production recovery.
Super Admin performs routine backup operations but receives no unilateral
production decryption authority. An authorized restore operator may decrypt
only after the required recovery approval and key-custodian release. Keep
private key material separate from the VPS, HDD, OneDrive, repository,
scripts, shell history, and logs. Define an audited key-recovery process,
custodian unavailability procedure, rotation/revocation, and how retained
recovery points remain decryptable until approved expiry. A key-recovery and
decryption rehearsal is required before any destination is operational.

After decryption, compare plaintext sizes and SHA-256 values with the
protected manifest before restore. Reject the entire recovery point on any
missing artifact, hash mismatch, failed decryption/authenticity check, or
manifest inconsistency; never restore a partial set as a complete recovery
point.

### Storage destinations and transfer

- **External HDD — PRIORITY / PROPOSED:** encrypt before writing; restrict
  physical and filesystem access; verify copied byte sizes and ciphertext
  hashes by read-back; then safely eject, disconnect, and record custody and
  location. Availability, capacity, physical separation, approved custody,
  and restore access are not yet verified. A connected or co-located HDD
  does not protect against ransomware, theft, or site loss.
- **Campus Microsoft 365 OneDrive — FALLBACK/LAST RESORT / PROPOSED:**
  dedicated SharePoint storage is unavailable and Graph automation is not
  provisioned. Use only a campus-owned account/folder after IT and Director
  approval, with folder access restricted to named authorized operators.
  Manual upload by the designated operator is the only planned transfer path;
  upload ciphertext only and verify remote byte sizes/hashes by an approved
  read-back. Retention, capacity, account recovery, audit, and failure-domain
  policy remain unknown. No personal OneDrive account is authorized by this
  specification.
- **VPS — SOURCE ONLY:** local staging is not an off-device copy. Do not leave
  plaintext archives in a webroot, Docker volume, or OneDrive-synchronized
  directory. Use restrictive staging permissions, minimize plaintext
  lifetime, and handle temporary data under an approved policy without
  claiming secure erasure where it is not provable.
- Mark a recovery point **COMPLETE** only when all encrypted artifacts and
  checksum index are present and independently verified on each approved
  destination. Never prune the last known-good point as part of a failed or
  partial run.

### Roles, audit, retention, and monitoring

| Responsibility | Super Admin / designated backup operator | Director Sekretariat/Rektorat | IT | Recovery key custodian |
|---|---|---|---|---|
| Routine backup execution, destination copy, hash/archive verification, and run monitoring | Responsible | Receives reports | Provides infrastructure/storage support | Not routine operator |
| Backup policy, media priority, access/retention policy, and production recovery approval | Supplies technical evidence; no self-approval | Accountable approver | Advises on institutional requirements | Advises on recoverability |
| Destination infrastructure, folder access controls, capacity, and storage recovery information | Follows approved controls | Approves policy | Responsible for institutional infrastructure/storage and confirms capabilities | No storage administration by default |
| Decryption-key custody and emergency key release | No unilateral access; requests authorized release | Approves key policy and appoints custodian | Supports approved infrastructure controls | Responsible for separately held key and audited recovery |
| Production restore/cutover | Executes only after approval and records evidence | Explicitly approves recovery point and production cutover | Supports infrastructure recovery | Releases key under the approved procedure |
| Deletion/retention exception | No unilateral pruning | Approves under policy and legal-hold requirements | Implements only approved storage actions | Ensures key-retention implications are understood |

These are operational duties, not new SITARA application roles or API
permissions. Super Admin's technical role does not confer Secretariat business
authority. Audit records should be retained separately from the source VPS
where feasible and record operator, approval reference, recovery-point ID,
timestamps, destination identifier, ciphertext hashes, validation result,
restore target, and failure/deletion events. Never log credentials, key
material, evidence contents, meeting contents, or raw storage keys.

Initial retention proposal, **not approved**:

- daily: 14 days;
- weekly: 8 weeks;
- monthly: 12 months.

The Director/policy owner must approve retention, legal holds, deletion
authority, and minimum recovery-point count. **Do not implement automatic
pruning** before written approval and a tested replacement/restore policy.
Monthly restore testing is also **PROPOSED**; its scope, owner, report, and
whether it must include both the priority HDD and the OneDrive fallback need
approval.
Monitoring should alert on missed schedules, non-zero command exits, stale
last-success time, insufficient space, failed hash/read-back, incomplete
manual OneDrive upload/read-back, missing HDD custody/check-in, key-recovery
failure, and overdue monthly restore test. RPO/RTO targets remain decisions
for the policy owner.

### Restore and disaster-recovery procedure

1. Record incident, authorize the recovery, and select a complete recovery
   point. Isolate the target from production and preserve the source package.
2. Verify the outer checksum index and encrypted artifact sizes/hashes on the
   selected destination.
3. Obtain the decryption identity through the separate approved key-recovery
   process; record approvals and key ID without logging key material.
4. Decrypt into a restricted disposable staging area and compare plaintext
   hashes to the encrypted inner manifest. Reject the set on any mismatch.
5. Restore PostgreSQL to an isolated disposable instance of the compatible
   major version. Recreate required roles/grants through approved provisioning;
   verify Alembic revision, schema, constraints/indexes, and non-sensitive
   counts against the manifest.
6. Safely extract the evidence archive into a private disposable root. Reject
   absolute paths, traversal, symlinks, duplicate entries, and any storage key
   outside the exact 32-hex format. Preserve private ownership/modes.
7. Reconcile database FILE metadata and scan history against regular files,
   sizes, digests, and manifest counts. Verify PENDING quarantine, REJECTED
   download denial, and CLEAN scan digest/file equality. Report LINK evidence
   as metadata-only; do not claim its target content was restored.
8. Produce a restore report with recovery-point ID, tool versions, revision,
   checks, discrepancies, status counts, approvals, and timings. Keep the
   source package immutable. Any production restore/cutover requires separate
   Director approval; never restore over main as part of a rehearsal.

### Readiness and work remaining

| Gate | Current status |
|---|---|
| Initial operational role decision and media priority (external HDD first; campus OneDrive fallback) | **AGREED AS DESIGN INPUT**; does not establish device/account availability or authorize backup/production restore |
| VPS provisioned and production storage path verified | **NOT VERIFIED**; VPS is not available |
| External HDD available, capacity/custody/location/access, and separate failure domain | **NOT VERIFIED / BLOCKED** |
| Campus Microsoft 365 OneDrive fallback, folder ACL, capacity/retention/recovery | **NOT VERIFIED / BLOCKED**; SharePoint library unavailable; manual upload only is planned |
| Microsoft Graph/Entra automation | **NOT AVAILABLE**; no Entra application provided by IT |
| Encryption tool and recipient-key design | **PROPOSED / BLOCKED pending approval, key custodian, and rehearsal** |
| Key recovery, rotation/revocation, authorized restore | **NOT VERIFIED / BLOCKED pending formal custodian and approval procedure** |
| Retention, deletion, monthly restore testing, audit, RPO/RTO | **PROPOSED / BLOCKED pending policy approval** |
| Main evidence schema/storage and coordinated source recovery point | **NOT READY**; current main revision/storage state above |
| Backup implementation, remote-copy verification, and restore rehearsal | **NOT IMPLEMENTED / NOT VERIFIED** |

Before any operational run, obtain written IT/policy approval, provision and
verify the destinations and key recovery, establish source write-quiesce
controls, then implement and test the backup workflow against disposable
resources. This specification does not authorize a main database migration,
evidence-volume provisioning, backup execution, or Stage 7.5.

### Stage 7.4.13 — Backup policy alignment

The approved design inputs now prioritize the external HDD as the planned
offline medium and campus Microsoft 365 OneDrive as a fallback/last resort.
SharePoint Document Library is unavailable; no Microsoft Entra ID application
for Graph has been provided, so OneDrive transfer is manual and ciphertext-
only. Folder access can be restricted, but retention, capacity, campus
recovery behavior, and the suitability of either medium for production remain
unverified. Neither medium is asserted to be available or production-approved.

The Director Sekretariat/Rektorat approves policy and production recovery;
Super Admin is responsible for backup operations and monitoring; IT provides
infrastructure/storage and confirms capabilities; a formally appointed
recovery key custodian holds and releases the decryption identity under
approved controls. The proposed `age` recipient-encryption design, separate
key recovery, and post-decryption digest verification remain subject to
institutional approval. Proposed retention remains 14 daily, 8 weekly, and
12 monthly points, with monthly restore testing. All are **PROPOSED**; do not
enable automatic pruning.

Database and evidence must still be captured as one quiesced recovery point.
The current main database lacks evidence metadata tables and the main evidence
volume is absent, so joint recovery remains **NOT VERIFIED**. This alignment
does not authorize backup creation, destination transfer, schema migration,
evidence-volume provisioning, or Stage 7.5.
