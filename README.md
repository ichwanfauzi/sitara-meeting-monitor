# SITARA — Merged Engineering Workspace

## Migration workspace note

This workspace uses the clean starter as the technical foundation and preserves legacy prototype entities separately for analysis. It is **not yet a full merge of the old prototype UI/API**. See `PROJECT_CONTEXT.md` and `docs/MIGRATION_PLAN.md` before implementing features. Do not use `backend/app/models/legacy_prototype.py` as production schema.

## Original starter guide

SITARA (sistem informasi tindak lanjut rapat dan arahan) — clean starter repository for a new implementation.
   
> **Important:** This is not a production-ready system. Backend foundations include Argon2id authentication, server-side sessions, login/logout/current-user endpoints, role-scoped Rapim metadata APIs, and Secretariat-only meeting transitions. Minutes revisions are append-only; a Secretariat review names the exact active revision, and `LIVE` to `FINAL` rejects a missing, invalid, or stale review. The first-stage revision editor is available for permitted users; real-time collaboration, decisions, task workflows, private document storage, and production deployment remain incomplete.

## Stack

- Frontend: React + TypeScript + Vite, ESLint, Prettier, Vitest, React Testing Library.
- Backend: FastAPI, Pydantic Settings, SQLAlchemy, Alembic, pytest, Ruff, mypy.
- Database: PostgreSQL through Docker Compose.
- Guardrails: Gitleaks, pre-commit, Semgrep, npm audit, pip-audit, GitHub Actions.

## Requirements

- Git
- Docker Desktop (or Docker Engine with Compose)
- Python 3.12+
- Node.js 22+ and npm
- Gitleaks
- Optional: pre-commit

## First-time setup (Windows PowerShell)

> `frontend/package-lock.json` is committed for reproducible installs. Use `npm ci` for local and CI setup; update the lockfile whenever `frontend/package.json` changes.

1. Copy `.env.example` to `.env`. The values are local development placeholders only.
   Generate a private limiter key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   and set `LOGIN_RATE_LIMIT_HMAC_KEY` in `.env`. Login returns `503` until this key is set.
2. Start PostgreSQL:
   ```powershell
   docker compose up -d postgres
   docker compose ps
   ```
3. Backend setup from the repository root:
   ```powershell
   py -3.12 -m venv backend\.venv
   backend\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e "./backend[dev]"
   ```
4. Run backend checks:
   ```powershell
   cd backend
   ruff check .
   ruff format --check .
   mypy app
   pytest
   cd ..
   ```
5. Start the API from the repository root (settings read `.env` from current directory):
   ```powershell
   $env:PYTHONPATH = "backend"
   python -m uvicorn app.main:app --reload --app-dir backend --no-proxy-headers
   ```
   Health endpoint: `http://127.0.0.1:8000/api/v1/health`. Interactive docs are development-only at `http://127.0.0.1:8000/docs`.
6. Frontend setup:
   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```
   The Vite development server proxies `/api/v1` to `http://127.0.0.1:8000`. The API's CSRF cookie is readable by the SPA at `/`; keep the frontend and API same-origin through this proxy locally and through the production reverse proxy.
7. Frontend quality checks:
   ```powershell
   npm run lint
   npm run format:check
   npm run test:coverage
   npm run build
   npm audit --audit-level=high
   ```

## Install the pre-commit hook

Install Gitleaks first from its official release/instructions: https://github.com/gitleaks/gitleaks

PowerShell:
```powershell
.\scripts\install-hooks.ps1
```

Git Bash / Linux / macOS:
```sh
sh scripts/install-hooks.sh
```

The hook blocks staged commits if Gitleaks reports findings or if the binary is unavailable. Hooks can be bypassed by a determined user, so CI scans remain mandatory. Do not commit credentials even if a scan passes.

Optional pre-commit checks (the installed `.githooks/pre-commit` runs them automatically if `pre-commit` is installed):
```sh
python -m pip install pre-commit
pre-commit run --all-files
```

## Branch and review policy

- Use a branch per feature; do not work directly on `main`.
- Open a pull request for each feature or meaningful change.
- Do not merge until CI passes and a human has reviewed security-sensitive changes.
- Do not give coding agents production credentials, unrestricted production SSH access, or real confidential meeting records.
- Never put real secrets in `.env.example`, documentation, fixtures, screenshots, prompts, or logs.

## Testing policy

- Use TDD: write a meaningful failing test, implement the smallest correct change, then refactor.
- Tests must check observable outcomes and negative cases, not only that a function was called.
- Review assertions and test data; a green result does not by itself prove useful coverage.
- Run integration tests against a dedicated test database, never production.
- The coverage thresholds are initial guardrails, not a replacement for test review.

## Database and migrations

- PostgreSQL is local development infrastructure only at this stage.
- Use Alembic migrations for schema changes; do not make untracked schema changes manually.
- Create a separate disposable test database for integration tests.
- Before production, add and test authorization policies/triggers for official status changes, audit history, and document access.

## Backup and rollback (before deployment)

- Back up PostgreSQL and private document storage as separate but coordinated assets.
- Encrypt backup files and store a copy outside the VPS/account hosting production.
- Define recovery point objective (RPO) and recovery time objective (RTO) with the institution.
- Restore backups into an isolated environment and verify the data, files, and permissions.
- Test a release rollback and a database recovery procedure before the first production deployment.
- Never test destructive migrations or restores on production data.

## Security review before production

- Complete authentication and server-side RBAC/object-level authorization.
- Confirm PIC cannot access full minutes/Decision Brief using direct URL, API, search, exports, or changed IDs.
- Enforce that only Secretariat can change an official task status, at the API and database boundary where appropriate.
- Add secure cookies/CSRF controls if cookie authentication is used, rate limiting, safe upload validation, and private file serving.
- Configure TLS, least-privilege DB credentials, firewall rules, secret rotation, security headers, and log redaction.
- Review every scanner finding; document any accepted exception. Do not automatically suppress findings to get a green build.

## Product and engineering documents

Read these before implementing a feature:

- [`docs/PRD.md`](docs/PRD.md) — problem statement, actors, business flows, functional requirements, business rules, and acceptance criteria.
- [`docs/system_design.md`](docs/system_design.md) — visual direction, color/typography tokens, role-aware navigation, UI components, page states, and document-export guidance.
- [`docs/architecture.md`](docs/architecture.md) — stack, module boundaries, data model, auth/security, API conventions, deployment, and recovery.
- [`docs/agents.md`](docs/agents.md) — detailed AI coding-agent workflow, tools, security, test, and reporting rules. The root [`AGENTS.md`](AGENTS.md) is the mandatory concise entrypoint.

These are draft v1.0 documents. Review explicit open decisions in each document before implementing policy-sensitive behavior.

## Current scope

Included: dashboard UI with clearly labeled synthetic data, FastAPI health and auth routes, role-scoped Rapim metadata API, identity/meeting/agenda/participant/versioned and structured minutes/review models, immutable Decision Brief draft versions and Alembic migrations, PostgreSQL-backed login rate limiting, tests, linter/type-check/test configuration, Docker PostgreSQL service, secret hook, and CI workflow.

Not included yet: account provisioning, complete authorization/RBAC, production migration rollout verification, real-time collaboration, Decision Brief review/approval/finalization, action item workflows, notifications, OCR, exports, final document templates, production Docker image, VPS deployment, and backup automation. The minutes editor loads agenda-bound discussions and decisions and appends complete immutable snapshots; legacy text revisions remain readable and are never auto-assigned to an agenda. Decision Brief drafts append immutable versions linked to the exact structured minutes revision and source decisions; stale state is derived at read time. Secretariat and leadership scoped to a meeting may create drafts, while PIC and Super Admin cannot read full minutes or briefs. During `LIVE`, only the designated notetaker may append a minutes revision. Super Admin also cannot use Secretariat review or lifecycle permissions.
