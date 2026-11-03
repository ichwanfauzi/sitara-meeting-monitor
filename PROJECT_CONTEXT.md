# SITARA — Project Context

## Purpose
SITARA manages Rapim meetings, live minutes, decisions, Decision Briefs, action items, PIC assignments, follow-up monitoring, documents, notifications, and audit history.

## Selected foundation
This workspace uses the engineering starter from `sitara_starter1.zip` as the base: React + TypeScript + Vite, FastAPI, SQLAlchemy 2.x, Alembic, and PostgreSQL. The legacy prototype concepts are preserved separately under `backend/app/models/legacy_prototype.py` for migration planning only.

## Important implementation status
This remains a migration workspace, not a production-complete application. It includes health/authentication, meeting and structured-minutes APIs, immutable Decision Brief drafts, and Action Item backend APIs for source-bound tasks, assignments, progress, official status history, verification, and evidence. Action Item operations apply role and organization scope; Super Admin is denied business access by default. Evidence files are stored privately with a 10 MiB per-file limit, start in `PENDING`, and are scanned by one internal Docker Compose worker using ClamAV. A file download requires an authorized actor, a latest `CLEAN` event for the stored SHA-256, and a fresh bounded read whose checksum still matches. Scanner/storage failures leave evidence quarantined. The frontend dashboard remains synthetic and is not connected to the Action Item APIs; account/organization provisioning, complete production-wide RBAC, real-time collaboration, Decision Brief approval/finalization, notifications, exports, and production operations remain incomplete. Unit/API tests use isolated SQLite; PostgreSQL concurrency tests require a disposable database. Production migration rollout and backup/restore have not been verified.

## Source-of-truth rules
1. Inspect current source before changing it.
2. `docs/sitara_schema_v1_draft.sql` is a draft reference, not an applied schema.
3. Do not connect legacy models to the production database until the draft schema and migration strategy are reviewed.
4. Never commit `.env`, local databases, `.venv`, `node_modules`, build artifacts, or real documents.
5. Only claim tests pass when actually run.

## Recommended next steps
1. Add supported account and organization provisioning, then complete production-wide RBAC policies.
2. Connect the dashboard to authorized meeting and Action Item APIs; keep frontend work separate from the completed backend evidence path.
3. Define Decision Brief review/approval/finalization authority and implement only after policy approval.
4. Add notifications, exports, a shared audit log, and reports under their approved policies.
5. Verify production migration, private-storage backup/restore, and operational monitoring procedures.
