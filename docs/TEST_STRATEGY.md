# SITARA Test Strategy

## TDD cycle

1. Write a test from the acceptance criterion before implementing the behavior.
2. Run it and confirm it fails for the expected reason (Red).
3. Implement the smallest correct change (Green).
4. Refactor and rerun focused tests and the full regression suite.
5. Review the test itself: assertions must fail for plausible incorrect implementations.

## Layers

- Unit tests: pure business rules, status transitions, validators, and permission predicates.
- API tests: HTTP status, request/response schema, validation failures, and authorization failures.
- Integration tests: database transactions, constraints, migration application, notifications, and document metadata.
- Email notification tests use a fake SMTP transport; verify generic copy, recipient override restrictions, retry limits, and that SMTP credentials never enter the API container. Never send test messages to a real mailbox in automated tests.
- End-to-end tests: representative journeys for Secretariat, leadership, and PIC.
- Security tests: direct URL/API access, object ID substitution, privilege escalation, upload abuse, and session protections.

The Decision Brief UI renders the reference table columns and resolves PIC, output, and target from the exact minutes revision bound to each saved version. Its print action must print only the selected version and keep its draft/approval and stale-source state visible.

## Important negative tests

- PIC cannot fetch full minutes or restricted Decision Briefs, even with a known UUID.
- Secretariat, Rektor, and Warek can read all meeting metadata, full minutes, and Decision Briefs; PIC/Super Admin and mixed-role variants remain denied.
- All active core users can append minutes revisions during `LIVE`; stale `base_revision_id` writes conflict. Global read access must not expand meeting metadata mutation, Decision Brief creation, or approval permissions beyond their existing scope.
- PIC and leadership cannot directly mutate the official task status.
- Only active, authorized Secretariat and Manager Legal accounts can perform an official status transition.
- Decision Brief approval is available to active, in-scope Secretariat, Manager Legal, Rektor, and Warek users. The version author cannot approve/reject their own submission; PIC and Super Admin remain denied server-side.
- Only Secretariat can record a minutes review; Super Admin remains denied even when also assigned Secretariat.
- `LIVE → FINAL` requires the latest `VALID` minutes review to name the active revision; a missing, invalid, or stale review must block without changing meeting status or writing a status event.
- Active Rektor, Warek, and Secretariat users can append minutes revisions during `LIVE`; stale `base_revision_id` writes conflict without overwriting. PIC and Super Admin, including mixed-role accounts, cannot retrieve full revision content.
- A stale `base_revision_id` and a review of a non-active revision are rejected. Composite database constraints prevent binding a review to another meeting's revision.
- Revision creation, review, and finalization serialize on the meeting row in PostgreSQL. Concurrent stale writers, revision/review races, revision/finalization races, and duplicate finalizations must preserve the active-revision review invariant.
- Database triggers reject revision update/delete; PostgreSQL also rejects `TRUNCATE`. Tests verify row mutation guards on SQLite migrations and all three operations on PostgreSQL.
- The minutes editor loads only authenticated meeting/revision API data, uses the active revision ID as `base_revision_id`, disables edits for PIC/Super Admin and non-LIVE meetings, and retains a draft after `409` until the user explicitly loads the newest revision.
- A `SELESAI` transition cannot happen without the required verification record.
- A decision marked `is_action_item = false` must not silently create a task.
- A task update cannot attach a document belonging to another task or meeting.
- A user cannot assign tasks outside their permitted organizational scope.
- Organization authorization rejects inactive users/units, missing or expired memberships, ended reporting lines for task access, unrelated leaders, unassigned PICs, and Super Admin accounts even when mixed with operational roles. Only active, authorized Secretariat and Manager Legal users may create/manage Action Items; Warek may monitor but not create follow-ups. Mixed-role PIC and Super Admin accounts do not inherit Secretariat/Manager Legal business authority.
- Disposition list and target-directory reads require an active Secretariat/Rektor/Warek identity in the requested meeting scope; PIC, Super Admin (including mixed-role), and unrelated leaders are denied. Directory responses must not expose email or credential fields.
- External meeting participants are stored as named records, not user accounts; only meeting editors can add or remove them, and those records never grant login or meeting access.
- Secretariat and in-scope Rektor/Warek assignment checks use current database roles and require the target PIC to be active with a current unit membership. Both may explicitly assign eligible PICs across unit boundaries; Rektor/Warek assignment still requires meeting-management scope. The PIC directory must return the same candidate set accepted by assignment validation. Reporting scope for task reads and progress traverses only currently effective lines and active members and fails closed when the manager's reachable reporting graph contains a cycle.
- Unauthenticated and disabled users cannot access protected endpoints.

## Database tests

Use a dedicated disposable PostgreSQL database. Run migrations from an empty database in CI. Never run tests that delete or mutate records against production.

`backend/tests/test_postgres_concurrency.py` is skipped unless `SITARA_TEST_DATABASE_URL` points to a disposable PostgreSQL database at migration head `0020_minutes_pic_suggestion`. It verifies the atomic login bucket upsert, expired-row cleanup, serialization of concurrent meeting transitions and Decision Brief approvals, minutes revisions/reviews/finalization, Decision Brief version creation, Action Item constraints, and evidence scan quarantine/append-only guards, including PostgreSQL `TRUNCATE` protection. Fixtures use synthetic records; the disposable test database can retain append-only rows until it is discarded. Do not point this variable at the development Compose database.

`backend/app/seed_initial_users.py` is a development/testing-only bootstrap. It accepts only an explicit local PostgreSQL URL whose database name ends in `_dev`, `_development`, `_test`, or `_testing`, and requires migration head `0028_meeting_external_attendees`. Run it only after independently creating and migrating a separate database. By default, it creates the seven initial leadership and Secretariat accounts with existing `REKTOR`, `WAREK`, `SEKRETARIAT`, and `MANAGER_LEGAL` roles in `REKTORAT`; it does not create Super Admin accounts. The opt-in `--include-demo-pics` mode is stricter: it requires `APP_ENV=testing` and a database name ending in `_test` or `_testing`, and adds only synthetic PIC A/B/C accounts in `SITARA-DEMO` plus reporting lines from every seeded Rektor/Warek to each PIC. Do not use this mode with development-shared or production data; the demo unit and users are not an approved organization roster. Passwords are random, hashed in the database, and written once to a new restricted credential file outside the repository. If the default seed already wrote its credential file, use a different `--credentials-file` for the newly created PIC accounts. Never commit or log credential files. No database seed was run for this change.

Action Item assignment creation, main PIC replacement, and supporting assignment ending write an allowlisted, redacted `action_item.assignment_changed` event in the same transaction. The audit payload excludes free-form assignment reasons. SQLite migration and API tests cover the payload and rollback behavior; PostgreSQL verification remains pending.

## Test quality review

For each changed test, review:

- Does it assert observable results rather than implementation details only?
- Would it fail if the authorization check were removed?
- Does it include at least one invalid/unauthorized input where relevant?
- Is the fixture representative without containing confidential data?
- Are time, random values, and external dependencies deterministic or controlled?

Coverage percentages are guardrails, not proof of correctness. For critical authorization/business rules, consider mutation testing after the initial feature suite is stable.

## Previous full PostgreSQL verification baseline (2026-10-15)

- Backend full suite with `SITARA_TEST_DATABASE_URL` pointing at the disposable PostgreSQL 16 database: 53 passed, 90.22% coverage, two Starlette/AnyIO deprecation warnings.
- PostgreSQL integration suite: 9 passed. Alembic upgrade to `0005_versioned_minutes`, downgrade to `0004`, re-upgrade, and `alembic check` passed. SQLite migration tests cover historical review preservation and append-only trigger behavior.
- `ruff check .`, feature-file `ruff format --check`, and `mypy app` passed. Repository-wide `ruff format --check .` still flags the pre-existing local `0003_meeting_workflow_login_rate_limit.py`; that migration was not reformatted as part of this feature.
- Frontend coverage tests: 2 passed; lint, format check, TypeScript build/type check, and Vite production build passed.
- `pip check`, `pip-audit --strict --skip-editable .`, and `npm audit --audit-level=high` passed with no dependency vulnerabilities. Gitleaks found no leaks in scanned source, tests, docs, and configuration. Semgrep was unavailable in this environment and was not run.

## Minutes editor verification (2026-10-21)

- Backend full suite using the isolated environment under `backend/.audit-venv-codex-20261015`: 44 passed, 9 PostgreSQL integration tests skipped because `SITARA_TEST_DATABASE_URL` was not set, 89.64% coverage, and two Starlette/AnyIO deprecation warnings. PostgreSQL migration/concurrency checks were not rerun for this frontend change; the 2026-10-15 PostgreSQL results above are the previous verified baseline.
- `ruff check .`, `ruff format --check app/api/routes/auth.py tests/test_auth.py`, `mypy app`, and `pip check` passed. `pip-audit --strict --skip-editable .` found no known vulnerabilities. Repository-wide `ruff format --check .` still reports the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- Frontend coverage tests: 13 passed (82.47% statements, 78.13% branches, 86.36% functions, 86.6% lines). ESLint, Prettier check, TypeScript build, Vite production build, and `npm audit --audit-level=high` passed; npm audit found no vulnerabilities.
- Gitleaks scanned the changed source, test, documentation, README, and project context paths with redaction enabled; no leaks were found. Semgrep was not installed in this workspace and was not run.
- `git diff --check` passed. No database schema, endpoint, or request/response schema changes were made. The CSRF cookie scope was broadened to `/` for the root SPA, and login/logout expire any legacy `/api/v1` CSRF cookie.

## Organization scope verification (2026-10-21)

- Backend `pytest -q`: 63 passed, 12 PostgreSQL-only tests skipped without a configured `SITARA_TEST_DATABASE_URL`, 89.94% total coverage, and five deprecation warnings. The PostgreSQL suite was run separately against a disposable PostgreSQL 16 container on `tmpfs`: 12 passed.
- PostgreSQL migration verification upgraded an empty database through `0008_organization_scope`, passed `alembic check`, downgraded the empty organization scope to `0007_decision_brief`, and upgraded to head again. SQLite migration tests verified empty downgrade safety, refusal to downgrade when an organization row exists, and preservation of that row.
- `ruff check .`, `mypy app`, `pip check`, and formatting checks for all changed Python files passed. Repository-wide `ruff format --check .` still fails only on the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- `git diff --check` passed. No frontend files or dependencies were changed, so frontend tests/build and dependency audit were not run for this stage. An independent read-only authorization/migration review found no bypass; it identified the need to keep organization provisioning gated on cycle/overlap validation and audit logging.

## Evidence hardening and backend dependency verification (2026-10-22)

- The backend manifest requires FastAPI `>=0.140.8` and pytest `>=9.0.3`; there is no backend lockfile. The system Python had FastAPI 0.115.0, Starlette 0.38.6, and pytest 8.3.3, so it did not satisfy the declared test environment. The previously failing login rate-limit test passed in the existing isolated environment with FastAPI 0.140.8, Starlette 1.3.1, and pytest 9.0.3; no dependency upgrade or test change was needed.
- Backend `pytest -q`: 115 passed, 14 PostgreSQL-only tests skipped because `SITARA_TEST_DATABASE_URL` was not configured, 85.15% coverage, and six warnings. PostgreSQL migration `0011` and trigger behavior were not verified in this run.
- `ruff check .`, `mypy app`, `pip check`, and `ruff format --check app tests` passed. Repository-wide `ruff format --check .` still reports the pre-existing formatting issue in `migrations/versions/0003_meeting_workflow_login_rate_limit.py`.
- No local PostgreSQL service/client was available, and the Docker CLI could not connect to a daemon. The Action Item evidence scan-result service has no configured antivirus engine or worker; files remain quarantined as `PENDING`, and downloads fail closed until a matching trusted `CLEAN` result exists.

## Initial development account provisioning (2026-11-12)

- After explicit approval, the local Compose PostgreSQL 16 development database was upgraded from `0001_identity_sessions` to `0012_user_job_title`; `alembic check` reported no metadata drift. The migration chain was inspected first and no downgrade was run.
- The database initially had five canonical roles, no users, and no organization tables. Read-only pre-seed checks confirmed all six target emails were absent. Provisioning created six initial leadership/Secretariat accounts, one `REKTORAT` unit, and six active memberships. Direct database checks verified the expected names, titles, roles, active state, unique generated credentials, and password hashes. No non-target users existed or were changed.
- The generated credential file was kept outside the repository and its Windows ACL was verified to allow only the current user. Credential contents were not logged or documented. The seed was not rerun because it has no dry-run mode; database state was checked directly instead.
- Authentication smoke verification used FastAPI `TestClient` with the persistent PostgreSQL database (in-process HTTP, not a separately running Uvicorn service): login, session cookies, `/auth/me`, CSRF rejection, CSRF-protected logout, and revoked-session rejection passed. One revoked session and a login rate-limit record remain as expected test effects.
- Backend `pytest -q` without `SITARA_TEST_DATABASE_URL`: 208 passed, 18 skipped, 84.24% coverage. Fifteen PostgreSQL concurrency tests were verified separately on a disposable PostgreSQL database before this persistent-database operation; they were not run against the development database. The other skips were two ClamAV harness tests and one Windows symlink test unavailable without elevated privileges. `mypy app`, `mypy app tests`, `ruff check .`, and Ruff formatting checks for the changed Python files passed. Frontend checks were not run because no frontend files changed.
- This verifies only the local development database and seed workflow; it does not verify production migration rollout, production provisioning, or production readiness.

## Stage 19 — Integration and security validation

- PostgreSQL 16 concurrency/integrity tests passed **18/18** against an approved disposable database at migration head `0017_decision_brief_approval`; append-only `TRUNCATE` protection was included. No development or production database was used.
- ClamAV daemon E2E passed for clean/infected synthetic evidence and scanner recovery. HTTP/Uvicorn E2E passed with the backend suite **234 passed, 36 skipped**, **84.35%** coverage, and **1 HTTP upload scenario passed**; disposable resources were cleaned up.
- Follow-up backend regression with `SITARA_TEST_DATABASE_URL` unset: **249 passed, 21 skipped**, **84.23%** coverage, and 9 warnings. The skips were 18 PostgreSQL-only tests (not run in this SQLite-only invocation), 2 ClamAV harness tests, and 1 Windows symlink test unavailable without elevated privileges; the PostgreSQL suite separately passed 18/18 above. Frontend: **105 tests passed**, ESLint, TypeScript/Vite production build, and Prettier check passed. Mypy `app` and `app tests`, Ruff lint/format, Semgrep `p/security-audit`, `pip-audit`, and the scoped redacted Gitleaks scan passed.
- Remaining gates: browser E2E was not run and no Playwright/Puppeteer dependency is installed; `npm audit` reports **7 moderate** transitive findings through `@typescript-eslint`/`minimatch`. A non-forced audit-fix dry-run proposed 14 transitive package updates but still reported all 7 findings; no dependency or lockfile change was made.
- Formatting/whitespace gates now pass: repository-wide `ruff format --check .`, frontend `npm run format:check`, and `git diff --check`. The format-only changes covered the 8 flagged Python files and `frontend/src/DispositionManagement.tsx`; the trailing whitespace at the end of `docs/PRD.md` was removed without changing its content. A root-wide Gitleaks `--no-git` scan reported 404 matches and was not treated as either a clean result or confirmed secrets; only the scoped redacted source/docs scan is clean.
- Stage 19 verification does not establish production readiness. Production migration rollout, deployment, backup/restore readiness, and browser-level E2E remain unverified.
