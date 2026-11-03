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

**Decision:** Only authorized Secretariat users may change an action item's official status. PIC and leaders submit progress updates; they do not directly change the official status.

**Reason:** Establishes a single accountable workflow for official monitoring status. This must be enforced server-side and tested.

## ADR-005: Meeting lifecycle and login attempt storage

**Decision:** Secretariat alone may transition a meeting. Persist each successful transition in `meeting_status_events` in the same transaction as the meeting update, with a row lock to serialize concurrent transitions. Permit `DRAFT → LIVE`, `LIVE → FINAL` after the latest valid review of the active minutes revision, and `FINAL → ARCHIVED`; reject all other transitions.

**Reason:** Status changes need attributable history. Minutes-review data and its limits are defined in ADR-006.

**Decision:** Store login attempt buckets in PostgreSQL using an HMAC digest of normalized login identity plus the ASGI client address. Use a fixed-window atomic upsert, a configured timeout, and fail closed with `503` if the limiter cannot operate. Delete expired rows during login and provide an operator cleanup command for idle periods. The supported local Uvicorn command disables proxy-header rewriting; deployments behind a proxy must explicitly allowlist trusted proxy addresses before enabling forwarded headers.

**Reason:** PostgreSQL coordinates workers/instances without adding Redis. HMAC prevents the bucket table from exposing raw email/IP pairs; expiry limits their retention. The default 10 attempts per 300 seconds is a configurable starting point that requires operational tuning.

## ADR-006: Minutes review attestation and finalization

**Decision:** Only an active user with the `SEKRETARIAT` role and without `SUPER_ADMIN` may record a minutes review. A reviewer may also finalize the meeting. Store each review as a separate record with the meeting, reviewer, sequence number, result, UTC timestamp, and optional note. The newest review controls finalization; `INVALID` blocks finalization until another review records `VALID`. Review and finalization lock the meeting row. Each review insert commits as one transaction; finalization commits the meeting update and status event together.

**Historical limitation (addressed by ADR-007):** Migration `0004` review records predate versioned minutes and have no revision reference. They remain in history after `0005`, but cannot satisfy finalization.

## ADR-007: Versioned minutes and revision-bound reviews

**Decision:** Store complete minutes snapshots in append-only `minutes_revisions` rows with stable UUID, meeting, per-meeting sequence, representation format, author, and UTC creation time. Format version 1 stores raw text; version 2 stores agenda-structured discussion and decision rows. The highest sequence is the active revision. No separate content hash or mutable “current revision” flag is used. Migration triggers reject updates/deletes to all snapshot rows; PostgreSQL also rejects `TRUNCATE`, which bypasses row-level triggers. Application writes append only. These guards protect against ordinary table mutations, not a database owner or superuser who can alter the triggers; production should separate the migration owner from a runtime role without DDL privileges.

During `LIVE`, only the designated notetaker may append a revision. Each write supplies `base_revision_id` for the active revision (or `null` for the first revision). The service locks the meeting row, compares that base with the current highest revision, and returns `409` for stale concurrent writes. Text snapshots reject blank text and allow at most 1,000,000 characters. Structured snapshots store no duplicate text content and cap aggregate submitted text at 1,000,000 characters.

For version 2, each discussion points to one agenda and one revision from the same meeting using composite foreign keys. Each decision points to a discussion within that exact revision. Child rows are complete snapshot records and have immutable update/delete/truncate guards. Revisions, discussions, and decisions are inserted in one transaction. Revisions do not copy prior child row IDs; a future action item can point to the exact decision snapshot that authorized its creation. Legacy text content is never migrated into an agenda automatically.

Each new review includes `minutes_revision_id`. A composite foreign key binds `(meeting_id, minutes_revision_id)` to a revision of that same meeting. Review creation locks the meeting and accepts only its active revision. Finalization takes the same lock and requires the latest review to be `VALID` and bound to the active revision. A later revision therefore invalidates prior reviews without changing the review history. Final status and its status event remain one transaction. The reviewer may finalize; only Secretariat without `SUPER_ADMIN` may review, start (`DRAFT → LIVE`), finalize, or archive (`FINAL → ARCHIVED`).

Full minutes content is returned only to authorized Secretariat or leadership users within meeting scope. PIC and Super Admin are denied even if they also hold another role. The editor uses the existing revision endpoint for legacy text and complete agenda-structured snapshots. Real-time collaboration is still out of scope.

**Migration impact:** `0005_versioned_minutes` adds revision rows and a nullable review reference so existing `0004` attestations are preserved without being silently assigned to a revision. Historical unbound reviews cannot finalize a meeting. `0006_structured_minutes` adds the format discriminator and child tables while preserving text and review rows. Its downgrade refuses to run while version 2 revisions exist; with no structured snapshots it restores the version 1 schema without losing text or review bindings. Production recovery should use a reviewed forward migration or verified backup/restore, never an unreviewed downgrade.

## ADR-008: Agenda-structured minutes snapshots

**Decision:** Extend the existing minutes-revision resource with an explicit representation version rather than creating parallel minute, discussion, or decision APIs. Version 1 retains `content` for all existing text revisions. Version 2 has `content = null` and contains a complete nested discussion/decision snapshot. The API keeps the existing revision endpoint, request base, authentication, CSRF, object scope, and notetaker/LIVE checks. Its response adds `format_version` and `discussions`; legacy content is returned unchanged with an empty discussion list.

Use revision-owned `minutes_discussions` and `minutes_decisions`. Composite foreign keys bind discussions to an agenda in the same meeting and decisions to a discussion in the same revision. The service validates agenda references before writing, then writes the revision, discussions, and decisions in one transaction. A stale `base_revision_id` or invalid scope writes no rows. Review records and finalization continue to bind to the active root revision ID, so any new snapshot makes earlier reviews stale without changing their history.

The editor shows legacy text readably and does not assign it to an agenda without an explicit user action. It sends one complete version 2 snapshot per save; conflicts retain the local draft and require an explicit reload of the newest revision. Decision rows represent source decisions only. Decision Briefs and action items remain separate domain modules; any future action item foreign key to decisions must remain non-unique because a decision may produce multiple tasks.

## ADR-009: Immutable, revision-bound Decision Brief drafts

**Decision (2026-10-21):** Represent each optional per-meeting Decision Brief as a sequence of `decision_brief_versions`, with a unique per-meeting version number. A version stores an editorial summary and notes plus `source_minutes_revision_id`; `decision_brief_decisions` records selected source decision IDs, display position, editorial priority label, and editorial note. Decision text remains in `minutes_decisions` and is returned through a join. Composite foreign keys require each version's source revision and every linked decision to belong to the same meeting and exact revision. Both tables are append-only; saving creates another version. The source revision must be the active revision when the version is created, protected by a meeting row lock. Staleness is computed on reads by comparing the stored source revision ID with the active minutes revision ID.

**Authorization:** Secretariat and leadership users (Rektor/Warek) who can read the meeting's restricted minutes may create draft versions. The backend also rejects PIC and Super Admin, including mixed-role accounts. The current minutes-revision endpoint supplies the source decision list; `GET /meetings/{meeting_id}/decision-briefs` reads version history and provenance, and `POST` appends one draft version with CSRF protection. No approval, ratification, or finalization workflow is implemented until its authority is decided.

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
