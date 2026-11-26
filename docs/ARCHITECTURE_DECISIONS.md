# Architecture Decision Records (initial)

## ADR-001: Modular monolith

**Decision:** Start with one FastAPI backend and one React frontend, structured into modules.

**Reason:** Fits a solo developer, reduces deployment complexity, and preserves clear boundaries without premature microservices.

## ADR-002: PostgreSQL

**Decision:** Use PostgreSQL for relational business data and transactional consistency.

**Reason:** SITARA has connected records, access controls, workflow transitions, and audit history.

## ADR-003: One notetaker writes during a live meeting

**Decision:** During a live meeting, only the designated notetaker may edit meeting notes; authorized leaders/viewers are read-only.

**Reason:** Matches the specified workflow and reduces concurrent-edit conflicts in the first release.

## ADR-004: Official status is controlled by Secretariat

**Decision:** Only authorized Secretariat and Manager Legal users may change an action item's official status. PIC and other leaders submit progress updates; they do not directly change the official status.

**Reason:** Gives the two operational managers shared authority for official monitoring status. This must be enforced server-side and tested.

## ADR-005: Meeting lifecycle and login attempt storage

**Decision:** Authorized Secretariat or Manager Legal users may transition a meeting. Persist each successful transition in `meeting_status_events` in the same transaction as the meeting update, with a row lock to serialize concurrent transitions. Permit `DRAFT → LIVE`, `LIVE → FINAL` after the latest valid review of the active minutes revision, and `FINAL → ARCHIVED`; reject all other transitions.

**Reason:** Status changes need attributable history. Minutes-review data and its limits are defined in ADR-006.

**Decision:** Store login attempt buckets in PostgreSQL using an HMAC digest of normalized login identity plus the ASGI client address. Use a fixed-window atomic upsert, a configured timeout, and fail closed with `503` if the limiter cannot operate. Delete expired rows during login and provide an operator cleanup command for idle periods. The supported local Uvicorn command disables proxy-header rewriting; deployments behind a proxy must explicitly allowlist trusted proxy addresses before enabling forwarded headers.

**Reason:** PostgreSQL coordinates workers/instances without adding Redis. HMAC prevents the bucket table from exposing raw email/IP pairs; expiry limits their retention. The default 10 attempts per 300 seconds is a configurable starting point that requires operational tuning.

## ADR-006: Minutes review attestation and finalization

**Decision:** Only an active user with the `SEKRETARIAT` or `MANAGER_LEGAL` role and without `SUPER_ADMIN` may record a minutes review. A reviewer may also finalize the meeting. Store each review as a separate record with the meeting, reviewer, sequence number, result, UTC timestamp, and optional note. The newest review controls finalization; `INVALID` blocks finalization until another review records `VALID`. Review and finalization lock the meeting row. Each review insert commits as one transaction; finalization commits the meeting update and status event together.

**Historical limitation (addressed by ADR-007):** Migration `0004` review records predate versioned minutes and have no revision reference. They remain in history after `0005`, but cannot satisfy finalization.

## ADR-007: Versioned minutes and revision-bound reviews

**Decision:** Store complete minutes snapshots in append-only `minutes_revisions` rows with stable UUID, meeting, per-meeting sequence, representation format, author, and UTC creation time. Format version 1 stores raw text; version 2 stores agenda-structured discussion and decision rows. The highest sequence is the active revision. No separate content hash or mutable “current revision” flag is used. Migration triggers reject updates/deletes to all snapshot rows; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. Application writes append only. These guards protect against ordinary table mutations, not a database owner or superuser who can alter the triggers; production should separate the migration owner from a runtime role without DDL privileges.

At adoption, during `LIVE` only the designated notetaker could append a revision. ADR-018 supersedes that edit gate: any active Secretariat, Rektor, or Warek may now append. Each write supplies `base_revision_id` for the active revision (or `null` for the first revision). The service locks the meeting row, compares that base with the current highest revision, and returns `409` for stale concurrent writes. Text snapshots reject blank text and allow at most 1,000,000 characters. Structured snapshots store no duplicate text content and cap aggregate submitted text at 1,000,000 characters.

For version 2, each discussion points to one agenda and one revision from the same meeting using composite foreign keys. Each decision points to a discussion within that exact revision. Child rows are complete snapshot records and have immutable update/delete/truncate guards. Revisions, discussions, and decisions are inserted in one transaction. Revisions do not copy prior child row IDs; a future action item can point to the exact decision snapshot that authorized its creation. Legacy text content is never migrated into an agenda automatically.

Each new review includes `minutes_revision_id`. A composite foreign key binds `(meeting_id, minutes_revision_id)` to a revision of that same meeting. Review creation locks the meeting and accepts only its active revision. Finalization takes the same lock and requires the latest review to be `VALID` and bound to the active revision. A later revision therefore invalidates prior reviews without changing the review history. Final status and its status event remain one transaction. The reviewer may finalize; authorized Secretariat or Manager Legal users without `SUPER_ADMIN` may review, start (`DRAFT → LIVE`), finalize, or archive (`FINAL → ARCHIVED`).

At adoption, full minutes content was limited to authorized Secretariat or leadership users within meeting scope. ADR-018 expands read access for all Secretariat, Rektor, and Warek users. PIC and Super Admin are denied even if they also hold another role. The editor uses the existing revision endpoint for legacy text and complete agenda-structured snapshots. Real-time collaboration is still out of scope.

**Migration impact:** `0005_versioned_minutes` adds revision rows and a nullable review reference so existing `0004` attestations are preserved without being silently assigned to a revision. Historical unbound reviews cannot finalize a meeting. `0006_structured_minutes` adds the format discriminator and child tables while preserving text and review rows. Its downgrade refuses to run while version 2 revisions exist; with no structured snapshots it restores the version 1 schema without losing text or review bindings. Production recovery should use a reviewed forward migration or verified backup/restore, never an unreviewed downgrade.

## ADR-008: Agenda-structured minutes snapshots

**Decision:** Extend the existing minutes-revision resource with an explicit representation version rather than creating parallel minute, discussion, or decision APIs. Version 1 retains `content` for all existing text revisions. Version 2 has `content = null` and contains a complete nested discussion/decision snapshot. The API keeps the existing revision endpoint, request base, authentication, CSRF, object scope, and LIVE checks. ADR-018 defines the current core-role write scope. Its response adds `format_version` and `discussions`; legacy content is returned unchanged with an empty discussion list.

Use revision-owned `minutes_discussions` and `minutes_decisions`. Composite foreign keys bind discussions to an agenda in the same meeting and decisions to a discussion in the same revision. The service validates agenda references before writing, then writes the revision, discussions, and decisions in one transaction. A stale `base_revision_id` or invalid scope writes no rows. Review records and finalization continue to bind to the active root revision ID, so any new snapshot makes earlier reviews stale without changing their history.

The editor shows legacy text readably and does not assign it to an agenda without an explicit user action. It sends one complete version 2 snapshot per save; conflicts retain the local draft and require an explicit reload of the newest revision. Decision rows represent source decisions only. Decision Briefs and action items remain separate domain modules; any future action item foreign key to decisions must remain non-unique because a decision may produce multiple tasks.

## ADR-009: Immutable, revision-bound Decision Brief drafts

**Decision (2026-10-21):** Represent each optional per-meeting Decision Brief as a sequence of `decision_brief_versions`, with a unique per-meeting version number. A version stores an editorial summary and notes plus `source_minutes_revision_id`; `decision_brief_decisions` records selected source decision IDs, display position, editorial priority label, and editorial note. Decision text remains in `minutes_decisions` and is returned through a join. Composite foreign keys require each version's source revision and every linked decision to belong to the same meeting and exact revision. Both tables are append-only; saving creates another version. The source revision must be the active revision when the version is created, protected by a meeting row lock. Staleness is computed on reads by comparing the stored source revision ID with the active minutes revision ID.

**Authorization:** Secretariat and leadership users (Rektor/Warek) who can read the meeting's restricted minutes may create draft versions. The backend also rejects PIC and Super Admin, including mixed-role accounts. The current minutes-revision endpoint supplies the source decision list; `GET /meetings/{meeting_id}/decision-briefs` reads version history and provenance, and `POST` appends one draft version with CSRF protection. Version-bound approval is defined separately in ADR-013; formal publication/finalization is still outside this decision.

**Editorial priority:** Store a required free-form label (maximum 100 characters) because no official priority scale for Decision Brief entries is defined. This is editorial metadata and does not change a source decision or task status.

**Migration impact:** `0007_decision_brief` adds the version and source-entry tables plus the composite uniqueness needed for source FKs. Downgrade refuses while a brief version exists. Existing text/structured minutes and review records are unchanged. Do not use `LegacyBase` prototype mappings for production.

## ADR-010: Effective-dated organization scope foundation

**Decision (2026-10-21):** Add production SQLAlchemy models `OrganizationUnit`, `UserUnitMembership`, and `ReportingLine`, with migration `0008_organization_scope` after `0007_decision_brief`. Memberships and reporting lines use UTC, half-open effective periods `[valid_from, valid_until)`. Unit parent links are optional; membership and reporting relationships allow multiple concurrent rows to support matrix organizations. No unit, employee membership, or reporting data is seeded because the approved organizational chart and roster were not supplied.

**Authorization helpers:** Resolve account activity and role codes from the database for each check. Operational Secretariat means an active user with `SEKRETARIAT` and without `SUPER_ADMIN`; that role may access task scope and assign only active PIC users with an active unit membership. PIC access is limited to the task's current server-loaded main/support assignments and requires an active unit membership. Active Rektor/Warek users may access task scope when a current transitive reporting path reaches its main PIC; every user on the path must have an active unit membership and account. A user carrying both a leadership role and `PIC` is limited to assigned PIC scope unless separately authorized as Secretariat. Super Admin is denied even when combined with Secretariat. A cycle in the manager's reachable reporting graph causes the helper to deny scope. Until a Secretariat unit is provided, Secretariat task authority is role-based rather than tied to an invented unit.

These helpers are authorization primitives, not Action Item endpoints. A future task service must load assignment IDs from persisted records, enforce decision/revision provenance, and apply operation-specific permissions. Only Secretariat may create tasks and assign PICs, including tasks sourced from draft decisions, as specified for the next phase; task status, reporting, evidence, and document access are not implemented here.

**Migration and provisioning:** The migration creates empty tables only. Foreign keys restrict deletion to preserve membership/reporting history, and downgrade refuses while any organization rows exist. Provisioning must wait for an approved unit chart and employee roster. Before production provisioning, a controlled workflow must validate interval overlap and hierarchy cycles and record auditable changes; the current schema prevents self-parent/self-reporting and invalid date intervals but does not enforce longer cycles or overlapping periods. No organization management API or audit-log model is added in this foundation stage.

**Policy requiring confirmation:** The narrow treatment of accounts holding both PIC and Rektor/Warek roles is a least-privilege default. Confirm whether such users should later receive leadership reporting scope in addition to assigned-task scope.

## 2026-10-14 — Product/UX/architecture documentation baseline

- Added `docs/PRD.md`, `docs/system_design.md`, `docs/architecture.md`, and `docs/agents.md` as draft v1.0 sources for business processes, UI patterns, architecture, and AI-agent governance.
- Root `AGENTS.md` is the tool-discoverable concise instruction entrypoint and links to `docs/agents.md`; a lower-case root `agents.md` is intentionally not created because Windows filesystems are commonly case-insensitive.
- Important schema correction before implementation: product requirements allow one decision to generate multiple action items. The draft SQL currently marks `action_items.decision_id` as unique, so that constraint must be removed in the final ORM/Alembic schema.
- The styling/PDF implementation details remain explicitly provisional where the starter does not yet have the associated dependencies or where official template fidelity needs a proof-of-concept.

## ADR-011: ClamAV image uses vendor-patched Ubuntu packages

**Decision (2026-10-30):** Build the ClamAV daemon image from the digest-pinned
Ubuntu 24.04 base and the signed Ubuntu snapshot `20261030T000000Z`. Install
Ubuntu's ClamAV 1.5.4 and FreshClam packages together with Ubuntu's fixed
`libxml2 2.9.14+dfsg-1.3ubuntu3.10` package. Do not replace libxml2 alone or
silence the CVE finding. Keep ClamAV as a separate non-root daemon, internal
TCP port 3310, persistent signature volume, and one existing scanner worker.

**Reason:** The official ClamAV Alpine 1.4.6/1.5.4 and Debian 13 1.4.6/1.5.4
images still contain a Scout-reported CVE-2026-86140 package. Ubuntu's
[security status](https://ubuntu.com/security/CVE-2026-86140) and
[USN-8787-1](https://ubuntu.com/security/notices/USN-8787-1) confirm a
distribution backport fixed Noble at `2.9.14+dfsg-1.3ubuntu3.9`. Ubuntu's
ClamAV and libxml2 packages are built for the same ABI and retain
`libxml2.so.2`; the final image was checked with `ldd`, ClamAV PING, FreshClam,
signature-version equality, daemon outage recovery, EICAR, HTTP upload, and
Docker Scout.

**Reproducibility and impact:** `backend/Dockerfile.clamav` pins the Ubuntu
base digest, package versions, and apt snapshot. No API, worker protocol,
database schema, migration, worker replica, or evidence-volume path changes.
The image's `clamav` UID/GID (100:101) matches the existing signature volume.
Update the snapshot/package/base inputs through review and repeat the scan and
E2E checks for future security updates. The signature healthcheck still does
not measure database freshness.

## ADR-012: Coordinated encrypted SITARA backups (specification)

**Decision (2026-10-31):** Specify PostgreSQL and private evidence as one
recovery point, captured while database writers, evidence uploads, and scan
result writes are quiesced. Use a binary-safe PostgreSQL custom-format dump
and a complete private evidence archive; record a recovery-point manifest and
SHA-256 checksums; encrypt artifacts before transfer; and verify restore of
the exact destination copy in an isolated disposable environment.

The planned priority medium is an external HDD for an offline copy; campus
Microsoft 365 OneDrive is a fallback/last resort. A dedicated SITARA
SharePoint Document Library is unavailable, and IT has not provided an
Entra ID application for Microsoft Graph. If approved, OneDrive upload is
manual by the designated operator, ciphertext-only, to a folder with
restricted access. HDD availability/capacity/custody and campus OneDrive
retention, capacity, recovery, audit, and failure-domain properties remain
unverified. Neither destination is asserted available or approved for
production. The future VPS is the source and is not yet available.

The proposed portable encryption method is recipient-based `age` with
institution-controlled key custody; an approved managed-key service may be
considered instead after a restore rehearsal. This is not a selected policy,
installed dependency, or generated key. Encrypt before writing/transferring;
hold the decryption identity separately under a formally appointed recovery
key custodian; and verify plaintext sizes/digests after authorized decryption.
Define recovery, rotation/revocation, and retained-backup compatibility before
operation. The Director Sekretariat/Rektorat approves backup policy and
production recovery; Super Admin is responsible for operations/monitoring; IT
is responsible for infrastructure/storage; the formally appointed custodian
controls key recovery. No operator self-approves production recovery or
retention deletion.

Proposed retention is 14 daily, 8 weekly, and 12 monthly recovery points, with
a monthly restore test. These are **PROPOSED** pending approval. Do not enable
automatic pruning. Retention, capacity, campus recovery policy, access audit,
RPO/RTO, and production restore require owner/IT decisions.

**Reason:** PostgreSQL metadata and private evidence files are separate
storage systems. A database-only snapshot cannot prove evidence recovery;
writer coordination, artifact integrity checks, and metadata/file
reconciliation are needed to preserve PENDING quarantine, REJECTED denial,
and CLEAN digest association.

**Status and impact:** This ADR records a technical specification only.
Backup scripts, encryption keys, destination integration, automated pruning,
and restore automation are not implemented. Existing main database,
Compose, schema, API contract, and volumes are unchanged. Stage 7.4.12 details
and acceptance gates are in [`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md).

## ADR-013: Version-bound Decision Brief approval workflow

**Decision (2026-11-16; approver roles clarified 2026-11-26):** Keep Decision
Brief content immutable and record workflow state as append-only events bound
to the exact Brief version and source minutes revision. Only a meeting-scoped
Secretariat, Manager Legal, Rektor, or Warek user may submit; submission is
allowed when performed by the version author or an authorized approver.
Submission requires a `FINAL` meeting and a `VALID` review of that exact source
revision. One eligible non-author may approve or reject a pending version;
rejection requires a reason. The author may withdraw only while pending, and
corrected content must be saved as a new version. Workflow and central audit
events are written in the same transaction while locking the meeting row.
Current state is derived from ordered events; no mutable approval status is
added to the Brief version.

**Reason:** Approval must be attributable to one immutable source-bound
version, prevent author self-approval, preserve rejection and resubmission
history, and avoid a successful business change without its audit record.

**Migration and verification impact:** Migration `0017_decision_brief_approval`
adds the event table, constraints, and append-only guards. SQLite workflow and
migration tests pass. Stage 19 ran the PostgreSQL 16 concurrency/integrity
suite against an explicitly approved disposable database: 18 tests passed,
including append-only `TRUNCATE` protection. Browser E2E remains unverified.
Database owners/superusers can still alter the schema or triggers; the
controls do not claim absolute immutability.

## ADR-014: Isolated synthetic PIC demo seed

**Decision:** Keep the existing `SEKRETARIAT` role, account, and job title
unchanged, along with the default six-account seed. An explicit
`--include-demo-pics` option may additionally
create synthetic PIC A/B/C users and a temporary `SITARA-DEMO` unit in an
isolated testing database only. Every seeded Rektor and Warek receives a
direct reporting line to each demo PIC so existing authorization helpers can
exercise the intended monitoring scope. The option requires `APP_ENV=testing`
and a local database name ending in `_test` or `_testing`; it is not available
for development, shared, or production databases. It adds no role, endpoint,
or authorization bypass, and does not establish a production organization
chart or roster.

**Reason:** The initial MVP demo needs to exercise leader monitoring with
placeholder PIC identities while real unit/PIC provisioning remains deferred.
The scope must remain synthetic and isolated rather than changing organization
or authorization policy for real users.

**Impact:** The seed continues to store unique password hashes and writes newly
generated credentials only to a new restricted file outside the repository.
When the initial six accounts already exist, the demo invocation requires a
separate credential-file path for the new PIC passwords. No database seed or
database operation was performed as part of this decision.

## ADR-015: Meeting-scoped leadership task assignment

**Decision (2026-11-16):** Operational Secretariat, active Rektor, and active
Warek may create Action Items and explicitly assign PICs across unit
boundaries. Secretariat without `SUPER_ADMIN` may assign any active PIC with an
active unit membership. Rektor/Warek without `SUPER_ADMIN` may create tasks
and assign any eligible active PIC only for meetings they are authorized to
manage as creator, chairperson, notetaker, or participant. The PIC directory
returns the same eligible candidates as the assignment service.
Accounts combining `REKTOR`/`WAREK` with `PIC` remain limited to PIC scope
unless separately authorized as operational Secretariat. Super Admin remains
denied even when combined with another role. Only authorized Secretariat may
change official Action Item status.

This decision supersedes ADR-010's Secretariat-only task creation and
assignment rule; its organization-scope, mixed-role, and Super Admin
restrictions remain in force.

**Reason:** PD-01 authorizes Rektor and Warek alongside Secretariat to create
and explicitly assign tasks across unit boundaries. Meeting scope remains a
server-side limit; reporting lines continue to limit leaders' task reads and
progress access.

**Impact:** The Action Item service, PIC directory, and frontend enforce these
permissions; tests cover cross-unit candidates and out-of-scope meeting
access. Migration `0018_action_item_unit_provenance` adds nullable provenance
columns for legacy compatibility. This decision does not grant leaders
official status-change authority.

**Amendment (seven-user operating roster):** Only active Secretariat and
Manager Legal users may create/manage Action Items or assign a PIC. Assignment
candidates are active users from the seven-user core roster (Secretariat,
Manager Legal, Rektor, and Wareks) with an active unit membership; no separate
PIC-role account is added to the roster. Rektor and Warek may be assigned and
retain their task-read scope, but cannot create or assign tasks. This amendment
supersedes ADR-015's earlier Rektor/Warek task creation and assignment grants.
PIC and Super Admin remain denied business permissions, including on mixed-role
accounts.

## ADR-016: Explicit Action Item unit provenance

**Decision (2026-11-16):** Store the work's responsible unit on
`action_items.responsible_unit_id` and store the selected PIC origin unit on
each `assignments.pic_origin_unit_id` row. This preserves the origin for each
assignment history entry, including supporting PICs and replacements. Both
columns are nullable for legacy records and are not backfilled. New task
creation requires an active responsible unit; each new assignment requires an
explicit origin selected from the PIC's active memberships. The backend
validates the membership at assignment time. Provenance is immutable after
the row is created.

**Reason:** PD-01 requires separate task responsibility and PIC origin
attribution. A PIC can have multiple active memberships, and choosing one
explicitly avoids silently assigning an organizational origin.

**Impact:** Migration `0018_action_item_unit_provenance` adds restrictive
foreign keys and lookup indexes. The authorized PIC directory returns active
unit choices without exposing email or credential data. Downgrade refuses
when provenance has been recorded. No database migration was run as part of
implementation.

**Implementation amendment (2026-11-26):** New Action Items do not require a
responsible unit; the field remains nullable and existing values are preserved.
If a client supplies a responsible unit, the backend validates that it is
active. User-account PIC assignments still require an explicit origin unit
selected from that PIC's active memberships; named PIC assignments remain
available without a verified origin unit, as there is no account membership to
validate. The PIC directory returns active units and membership-scoped origins
to authorized meeting officials.

## ADR-017: Redacted Action Item assignment audit events

**Decision (2026-11-16):** Record assignment creation, main PIC replacement,
and supporting PIC ending as `action_item.assignment_changed` audit events.
Each event records the Action Item, operation, assignment and PIC IDs, role,
origin unit, actor, database-verified actor roles, and correlation ID where
available. Free-form assignment reasons are excluded. The event is inserted in
the same transaction as the assignment and version change; failure rolls back
the business mutation.

**Reason:** Assignment history preserves who held responsibility and when,
while the central audit trail identifies who made the change and which
organizational origin was selected. Free-form reason text may contain details
that should not be copied into the general audit log.

**Impact:** Migration `0019_assignment_audit` extends the audit
action/object constraints and recreates SQLite append-only guards after the
table rebuild. Downgrade refuses after assignment audit events exist. SQLite
API and migration tests passed; PostgreSQL and runtime migration verification
remain outstanding.

## ADR-018: Core-role Rapim visibility and live minutes editing

**Decision (2026-11-18):** Active Secretariat, Rektor, and Warek users may read
all Rapim metadata, full minutes, and Decision Briefs. PIC and Super Admin
remain denied, including on mixed-role accounts. Any of the three core roles
may append minutes revisions while a meeting is `LIVE`. The per-meeting
notetaker identity may vary and is retained for attribution; it is not an
exclusive edit permission. Every write remains append-only and supplies the
active `base_revision_id`, so concurrent stale writes receive a conflict.

The expanded read scope does not expand write scope for meeting metadata,
agendas, participants, or Decision Brief creation. Those mutations retain the
existing meeting-management scope. Rektor/Warek retain their existing scoped
Action Item management rights, and Secretariat remains the cross-meeting
monitoring owner and the only role that changes official task status.

**Reason:** Rapim records and decisions are institution-wide reference
information for the three core roles. A single fixed editor account is not
needed; revision locking already prevents stale snapshots from overwriting
newer minutes.

**Impact:** Meeting list/detail, full-minutes reads, and Decision Brief reads
use global core-role scope. `can_manage_meeting` and Decision Brief creation
remain separately scoped. No schema migration is required; the existing
`notetaker_id` continues to identify the notetaker for each meeting.
This decision supersedes ADR-003 and the single-writer and restricted-read
rules recorded in ADR-007, as well as the previous meeting-scope restriction
for core-role reads. It does not change the prior write scope for meeting
metadata or Decision Brief creation.

## ADR-019: Table-based minutes and PIC suggestions

**Decision (2026-11-18):** Structured minutes use a table for entry and a
matching saved-data preview with the columns Agenda/Pokok Bahasan,
Putusan/Arahan & Tindak Lanjut, PIC, and Target. Each source decision may store
an optional free-text PIC suggestion. The suggestion is descriptive only;
official assignments continue to be recorded as Action Items with their own
assignment history. Decision Brief remains an editorial summary derived from
the source minutes.

**Reason:** The meeting record is easier to enter and review when its result
fields follow the familiar institutional minutes table. Keeping suggestions
separate from task assignment avoids confusing a name written in meeting
minutes with an accountable, history-tracked assignment.

**Impact:** Migration `0020_minutes_pic_suggestion` adds a nullable,
300-character column to `minutes_decisions` without backfill. The editor always
uses the table form; legacy text revisions remain intact and appear as an
expandable read-only source. Their content is not copied or mapped to agenda
fields automatically. The print action uses only the latest saved structured
revision. Downgrade refuses while suggestions remain. The migration has not
been applied to a shared or production database.

**Amendment (2026-11-25):** Keep all decisions for one discussion together in
one visual table row. Number the decisions within the Putusan cell and show
their corresponding PIC, Output, and Target values in their own cells without
repeating the decision number in those columns. The printed minutes table
includes a `No.` column and follows the supplied landscape notula example.
Target Penyelesaian may be entered as a date or manual text, with at most 500
characters. This adds `minutes_decisions.target_text` while preserving the
existing `target_date`; both values cannot be populated together. Migration
`0023_minutes_manual_target` adds this nullable field without backfill and
refuses downgrade while manual targets exist. The target value remains part of
the immutable source minutes revision and is shown in Decision Brief from that
same revision.

## ADR-020: Table-based Decision Brief preview

**Decision (2026-11-18):** Match the supplied Decision Brief example with a
dated `DECISION BRIEF RAPAT PIMPINAN` heading and a result table containing
No., Bahasan, Putusan/Tindak Lanjut, PIC, Output, and Target Penyelesaian.
Each saved brief version resolves these values through its exact source
minutes revision; a later active revision must not rewrite an older preview.
Keep editorial summary, priority, notes, approval state, and stale-source
provenance visible alongside the table. Printing targets one selected version
and labels its approval state so a draft is not presented as a final document.

**Reason:** Rapim users can scan and print decisions in the same familiar
row-and-column format used by the institution while retaining the source and
approval history already enforced by the versioned Decision Brief model.

**Impact:** Frontend presentation and print styles only; no schema or API
change. The formal publication/finalization workflow remains unchanged.

**Amendment (2026-11-25):** For newly created versions, retain the exact
source decision relation but enter a separate, initially blank
Putusan/Tindak Lanjut summary. Bahasan, PIC, Output, and Target are resolved
from the exact minutes revision. The full source decision text is not copied
into the new Decision Brief row, and the previous summary/priority/note inputs
are removed from this table workflow. The version still remains immutable and
creates a new version on correction. Since priority is no longer entered in
this workflow, new rows may store a blank priority; existing editorial
priorities remain unchanged. This supersedes ADR-009's required-priority rule
for newly created versions.

**Migration impact:** Migration `0027_brief_optional_priority`
relaxes only the priority check constraint. It preserves existing values and
the append-only guards; downgrade is refused if blank-priority rows exist.

## ADR-021: Seven-user Rapim workflow and structured minutes entry

**Decision (2026-11-23):** The intended core roster is the Rektor, four
Wareks, Director of Secretariat, and Manager Legal. Active Secretariat,
Manager Legal, Rektor, and Warek users may read all Rapim records. Secretariat,
Manager Legal, and Warek may create/manage meetings; active Secretariat,
Manager Legal, Rektor, and Warek users may edit LIVE minutes. Secretariat and
Manager Legal control meeting status. Only Secretariat and Manager Legal may
create/manage Action Items; Warek may not create follow-ups. Official
task-status authority is shared by Secretariat and Manager Legal.

Meeting chair identity, handover, disposition, and lifecycle panel are removed
from the user flow. Notetaker is optional and selected from the active core-user
directory at meeting creation for attribution only; it is not an edit gate.
Participants are selected from the active user directory; agenda numbering is
automatic; agenda PIC values are free text.
Meeting number remains editable in every meeting status by meeting editors,
with the existing version lock and audit event. Other meeting metadata remains
editable only while `DRAFT` or `LIVE`.

Minutes use a landscape table entry/output format. SITARA does not record,
upload, or play meeting audio and has no transcription workspace or ChatGPT
integration. Editors enter prepared meeting points into the structured table
and review them before saving official minutes. Any future AI integration must
be approved by the institution and keep AI output as a human-reviewed draft.
Every source decision must be represented in the linked Decision Brief. Action
Item PICs may be selected from eligible active core-roster accounts or entered
as free text. Only Secretariat and Manager Legal may create/manage tasks or
assign PICs; Rektor and Warek are eligible assignees but not assigners. New
tasks do not require a responsible unit; account PIC assignments require a
membership-validated origin unit, while named PICs have no verified origin.
Assignment reasons remain optional and are kept out of the audit event.

**Reason:** This follows the confirmed seven-user operating model, keeps
meeting control with Secretariat, gives Wareks meeting access without task
creation authority, and preserves human review of confidential meeting content.

**Impact:** Migration `0021_meeting_roster_pic` adds the Manager Legal role,
agenda PIC suggestions, and named Action Item assignments while preserving
legacy identity/unit columns and audit history. No Herry account is provisioned
until an official work email is available. Account creation remains an
administrative step and must not use invented credentials or identity data.

## ADR-022: Manager Legal operational authority and local development account

**Decision (2026-11-24):** Manager Legal has the same operational authority as
Sekretariat for Rapim, including meeting lifecycle/review controls, minutes
review, Action Item creation and management, official task-status changes, and
completion verification. The role remains separate from Super Admin; PIC and
Super Admin permissions stay denied, including for users with mixed roles.
Provision the local Manager Legal account with the synthetic address
`herry.zulkarnaen@users.sitara.test`, the `MANAGER_LEGAL` role, and current
membership in `REKTORAT`. Its generated password is stored in a restricted
local credential file. Production account provisioning still requires an
official work email.

**Reason:** The user confirmed Manager Legal should operate SITARA with the
same business permissions as Secretariat and approved matching the local
development account pattern used by the seeded accounts.

**Impact:** No schema migration is needed because migration
`0021_meeting_roster_pic` already defines `MANAGER_LEGAL`. The local account
seed now includes Manager Legal. Existing Secretariat-only operational
policies are superseded for this role; Super Admin remains technically
separate and does not inherit these business permissions.

When Sekretariat or Manager Legal ends a supporting assignment, the interface
asks for confirmation twice before sending the request. Assignment history and
the backend's existing authorization and audit behavior remain unchanged.

## ADR-023: Active Action Items, Repository, and PIC deadline reminders

**Decision (2026-11-25):** Keep unfinished, non-deleted Action Items in the
operational list. Verified `SELESAI` items and soft-deleted items appear in the
Repository. The Repository combines meeting, agenda, minutes, Decision Brief,
and completed follow-up navigation with keyword, category, year, and scope
filters. Repository access continues to use existing meeting and task
authorization; PIC users see only their assigned tasks and do not gain access
to minutes or Decision Brief content.

PIC users see an in-app dashboard reminder for assigned tasks that are overdue
or due within seven days. This display does not send email, make external
service calls, or change official task status.

**Reason:** Users need a short active task list and one searchable place for
final meeting records and completed follow-ups, while keeping task history and
restricted meeting content protected.

**Impact:** Action Item deletion is a soft delete with a version increment and
append-only audit event. Editing is limited to authorized Secretariat and
Manager Legal users and does not change a task's source decision or official
status. Migration `0022_repository_action_item_edits` stores deletion metadata
and a separate Decision Brief editorial text field. Existing full decision
text remains attached to its exact minutes revision; new brief text is entered
separately while Bahasan, PIC, Output, and Target are resolved from that
revision.

**Amendment (2026-11-25):** The Repository landing page lists meetings only.
Selecting a meeting opens its related agenda, minutes, Decision Brief versions,
and Action Items together in a meeting detail view. Landing-page filters apply
to meetings (keyword, year, and final/archive scope), not document categories.
The detail view continues to honor existing endpoint authorization: PIC users
remain in Tugas Saya and cannot read full minutes or Decision Brief content.

## ADR-024: Direct editing with internal content audit

**Decision (2026-11-25):** The minutes and Decision Brief editing screens show
the current saved content in one editable form and do not show revision,
version, or draft history. Decision Brief fields are prefilled from the latest
saved brief tied to the active minutes revision; Bahasan, PIC, Output, and
Target continue to come from that exact source revision. A save creates the
next immutable source-bound snapshot internally. Historical snapshots are
retained because Action Items and approval events reference exact source
records; the operational screen does not offer deletion of those records.

Each successful minutes or Decision Brief save appends a content-free
`audit_events` record in the same transaction as the saved snapshot. The event
contains actor and role, meeting/source identifiers, revision or version
number, format, and decision count. It never contains meeting text, editorial
text, or attachment contents. This audit data is for database administration
and is not shown as an operational history panel.

**Reason:** Users can correct the current document through the familiar form
without exposing technical version terminology, while exact source links,
approvals, and task provenance remain intact and changes remain auditable.

**Impact:** Migration `0024_content_audit_events` expands the central audit
allowlist for minutes and Decision Brief saves. Its downgrade refuses while
these audit events exist. Existing document snapshots and task references are
not deleted or rewritten.

## ADR-025: Rapim-first document navigation and task detail disclosure

**Decision (2026-11-25):** The Notulensi and Decision Brief landing screens
show the accessible Rapim list first. Selecting a Rapim opens its corresponding
editing workspace directly, without a second meeting search control in the
selected-meeting editor; returning to the list is how users choose another
Rapim. The Action Item workspace starts with its create
action and task list; selecting a task opens its details in a modal. Dashboard
task cards show the title, status, and PIC, with detailed information available
from the same modal. The dashboard does not show a separate recent-meetings
list.

Agenda remains available for planning. Minutes capture what was actually
discussed and do not derive discussion text from agenda titles.

**Reason:** Users who return to a meeting document can find the Rapim before
editing, and operational pages stay focused on the next action. Details remain
available on demand without making every task card a dense report.

**Impact:** Frontend routing and presentation only; no API, database, or role
authorization change. Route state tracks the selected meeting or task so links
within the same menu open the requested record without a full-page reload.

## ADR-026: Recipient-scoped in-app notifications

**Decision (2026-11-25):** Persist in-app notifications for directly related
users only. Action Item status changes notify active assigned PICs. Decision
Brief review events notify the relevant author and eligible reviewer. Messages
remain generic and exclude task/meeting titles, restricted document content,
and rejection reasons. Users can list only their own notifications and mark
only their own records as read. The top-bar center displays the unread count
and links to the relevant authorized workspace; target APIs continue to
enforce object-level access.

**Reason:** Deliver actionable updates without disclosing restricted meeting
content or broadening recipient access beyond the people directly involved.

**Impact:** Migration `0025_in_app_notifications` adds durable notification
records with per-recipient event deduplication. Status/workflow events create
notifications in the business transaction. Email, external delivery, and
automated due-date reminders are not part of this implementation.

## ADR-027: Optional SMTP delivery for notification events

**Decision (2026-11-26):** Add optional email delivery for newly created
notifications. Email delivery is disabled by default. When enabled, the API
marks new notification records as pending in the same business transaction;
a separate, single-replica worker sends them through authenticated SMTP with
STARTTLS and bounded retries. Existing in-app notifications are migrated as
email-disabled and are not sent retroactively.

The email uses a fixed generic subject and fixed copy selected by notification
type. It does not include free-form notification text, meeting/task metadata,
document content, or object identifiers. Production delivery goes to the
notification recipient's account email. A test-recipient override is allowed
only in development/testing and fails configuration validation in other
environments. SMTP credentials are provided only to the worker through
environment configuration; the API does not receive the SMTP password.

**Reason:** Provide email alerts without making a successful status/review
transaction depend on SMTP availability or disclosing restricted meeting
content. Delivery failures remain durable and retryable.

**Impact:** Migration `0026_notification_email_delivery` adds email state,
attempt, and retry fields to notifications. The opt-in Compose profile
`notification-email` gives the worker outbound SMTP access while keeping SMTP
credentials out of the API service. Gmail trials use `smtp.gmail.com:587` and
a locally configured Google App Password. No sender credential is stored in
the repository; actual delivery requires local SMTP account configuration.

## ADR-028: Named external meeting participants

**Decision (2026-11-26):** Meeting editors may record attendees who do not
have SITARA accounts by entering a name through the `Lainnya` participant
option. Store these entries separately from `users` and `meeting_participants`.
They are visible only through the existing authorized meeting response and do
not create an account, role, login, or additional meeting access. Add/remove
operations use the same meeting-edit authorization, version check, and audit
event as registered participants; audit payloads identify the external record
without copying its name.

**Reason:** Meeting participant records should represent actual attendees
without requiring an account or inventing an identity. Keeping guest names
separate prevents them from being mistaken for authenticated users.

**Impact:** Migration `0028_meeting_external_attendees` adds
`meeting_external_participants` with a guarded downgrade when entries exist.
The API returns these names separately from account-backed participants.
