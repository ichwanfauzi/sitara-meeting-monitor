# SITARA — Project Context

## Purpose
SITARA manages Rapim meetings, live minutes, decisions, Decision Briefs, action items, PIC assignments, follow-up monitoring, documents, notifications, and audit history.

## Selected foundation
This workspace uses the engineering starter from `sitara_starter1.zip` as the base: React + TypeScript + Vite, FastAPI, SQLAlchemy 2.x, Alembic, and PostgreSQL. The legacy prototype concepts are preserved separately under `backend/app/models/legacy_prototype.py` for migration planning only.

## Important implementation status
This remains a migration workspace, not a production-complete application. It includes health/authentication, meeting and structured-minutes APIs, immutable Decision Brief versions with version-bound review, and source-bound Action Items with assignments, progress, official status history, verification, evidence, and audit events. Active Secretariat, Manager Legal, Rektor, and Warek users can read full minutes and Decision Briefs; PIC and Super Admin remain denied. During `LIVE`, active Rektor, Warek, and Secretariat users can append minutes revisions; the optional notetaker is recorded for attribution, while `base_revision_id` guards stale writes. Secretariat and Manager Legal share operational authority for official Action Item status; Rektor/Warek retain their scoped task-management rights. Decision Brief submission requires a FINAL meeting and a VALID review of the exact source revision; an authorized in-scope Rektor, Warek, Secretariat, or Manager Legal user may submit, while the author cannot approve their own version. Approval workflow and central audit events are persisted transactionally. Notifications support in-app delivery and optional SMTP through a separate worker; email is disabled by default. Stage 19 verified PostgreSQL 16 concurrency/integrity for the workflow using a disposable database; browser E2E remains unverified. Action Item operations apply role and organization scope; Super Admin is denied business access by default. Evidence files are stored privately with a 10 MiB per-file limit, start in `PENDING`, and are scanned by one internal Docker Compose worker using ClamAV. Downloads require authorization, a latest `CLEAN` event for the stored SHA-256, and a fresh bounded read whose checksum still matches; scanner/storage failures leave evidence quarantined. A development/testing-only seed command provisions seven synthetic core accounts, but this is not production account provisioning. Production-wide RBAC rollout, real-time collaboration, OCR, exports, deployment, migration rollout, and backup/restore remain unverified. Unit/API tests use isolated SQLite; PostgreSQL concurrency tests require a disposable database.

## Source-of-truth rules
1. Inspect current source before changing it.
2. `docs/sitara_schema_v1_draft.sql` is a draft reference, not an applied schema.
3. Do not connect legacy models to the production database until the draft schema and migration strategy are reviewed.
4. Never commit `.env`, local databases, `.venv`, `node_modules`, build artifacts, or real documents.
5. Only claim tests pass when actually run.

## Recommended next steps
1. Define production-approved account and organization provisioning, then complete production-wide RBAC policies.
2. Complete browser E2E against synthetic data and keep authoritative source and version history immutable.
3. Add OCR and exports only under approved human-review and authorization policies.
4. Verify production migration, private-storage backup/restore, and operational monitoring procedures.
