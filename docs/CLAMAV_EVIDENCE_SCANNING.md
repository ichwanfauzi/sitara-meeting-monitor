# ClamAV evidence scanning runtime

The main `docker-compose.yml` runs PostgreSQL, the FastAPI API, ClamAV, and one
`evidence-scanner` process. The API and scanner use the same `DATABASE_URL` and
private `sitara_action_item_evidence` named volume. The API mounts that volume
read/write; the scanner mounts it read-only. The API is published on loopback
only. ClamAV port 3310 is available on the Compose network and is not published
to the host. Uploads are limited to 10 MiB per file and 11 MiB per multipart
request; each file starts in quarantine as `PENDING`.

Compose uses explicit isolated networks rather than the implicit default:
API/PostgreSQL and worker/PostgreSQL use separate internal database networks;
the worker and ClamAV share an internal scanner network; ClamAV alone also
joins an egress-capable network for FreshClam signature updates. PostgreSQL
does not join the scanner network, and API does not join the scanner network.
The HTTP E2E Compose mirrors these service boundaries with uniquely named
disposable networks.

The backend image runs as UID/GID 10001. Its image creates the evidence path
with mode `0700`; Docker initializes an empty named volume from that directory
on first mount. The queue does not atomically claim or lease pending rows. The
result writer locks the evidence row to prevent duplicate terminal events, but
it does not prevent duplicate ClamAV work if worker processes overlap. Keep
exactly one scanner replica until atomic queue claims/leases and worker-level
concurrency tests are implemented.

The worker opens regular files without following a final symlink, checks size
before reading, reads at most `10 MiB + 1` bytes, and compares file metadata
before and after the read. It hashes the bytes actually read and checks that
digest against the upload metadata before sending them to ClamAV. Missing,
oversized, mutated, or checksum-mismatched files remain quarantined. Downloads
require an authorized user and a latest `CLEAN` result for the stored digest;
the API bounds the read and verifies size and SHA-256 again before returning
the attachment. The `clamdscan --ping=3` healthcheck confirms daemon
availability only; it does not verify that signatures are fresh.

## ClamAV container security

The service builds `sitara-clamav:1.5.4-ubuntu24.04` from
[`backend/Dockerfile.clamav`](../backend/Dockerfile.clamav). The Ubuntu 24.04
base is pinned by digest; package installation uses the signed Ubuntu snapshot
`20261030T000000Z` and exact ClamAV/libxml2 package versions. ClamAV 1.5.4,
FreshClam, `clamdscan`, and libxml2 are Ubuntu Noble packages rather than a
manually overlaid shared library.

The CVE is in upstream libxml2 versions before 2.15.4. Ubuntu's official
[CVE status](https://ubuntu.com/security/CVE-2026-86140) and
[USN-8787-1](https://ubuntu.com/security/notices/USN-8787-1) mark Noble
`libxml2` fixed from `2.9.14+dfsg-1.3ubuntu3.9`; this image pins
`2.9.14+dfsg-1.3ubuntu3.10`. The vendor backport retains `libxml2.so.2`.
Ubuntu's `libclamav12` package is built in the same distribution package set
and resolves that SONAME; `ldd /usr/sbin/clamd` showed the resolved library with
no missing dependencies. No ABI-incompatible upstream library was copied over
the image.

The image and Compose service run as `clamav` UID/GID 100:101, matching the
existing Alpine image and signature-volume ownership. The entrypoint runs
FreshClam and `clamd` as that non-root user, performs an initial database
download only for an empty database volume, and manages both foreground
processes. FreshClam checks daily and notifies `clamd` to reload after updates.

ClamAV port 3310 is exposed only inside the Compose network. The
`clamdscan --ping=3` healthcheck verifies that `clamd` responds; after a
FreshClam update the daemon must report the same signature version as the
database files. The healthcheck alone does not measure signature freshness.

## Stage 6B image decision and verification (2026-10-30)

### Root cause and candidate evaluation

The official [ClamAV 1.5.4 release](https://github.com/Cisco-Talos/clamav/releases/tag/clamav-1.5.4)
and `clamav/clamav:1.4.6`/`:1.5.4` Alpine images contain
`libxml2 2.13.9-r2`; Docker Scout reports CVE-2026-86140 HIGH with no fixed
version. The official `:1.4.6-debian13-slim` and
`:1.5.4-debian13-slim` variants contain Debian's vulnerable Trixie libxml2
package as well. This matches the
[Alpine tracker](https://security.alpinelinux.org/vuln/CVE-2026-86140) and
[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-86140);
changing ClamAV image tags alone does not remediate the package.

| Candidate | Findings and trade-offs | Decision |
|---|---|---|
| Official ClamAV Alpine/Debian images | ClamAV release tags still contain the vulnerable distro packages; Scout marks the target HIGH. Low maintenance, but not currently fixed. | Rejected |
| Rebuild ClamAV source against upstream libxml2 2.15.4 | Can keep ClamAV as a daemon and build both sides together, but adds source-build, toolchain, ABI, and ongoing patch-maintenance burden. | Not needed |
| Ubuntu 24.04 ClamAV + libxml2 packages | Ubuntu publishes [ClamAV](https://launchpad.net/ubuntu/noble/+source/clamav) 1.5.4 and a fixed [libxml2](https://launchpad.net/ubuntu/noble/+source/libxml2) backport. Both come from one signed, version-pinned package snapshot and use the same distro ABI. | Selected |

The selected image avoids the risky “replace only libxml2” workaround. It
continues to expose the same ClamAV TCP protocol on internal port 3310; the API
contract, worker count, schema, and scanner/database volume are unchanged.
FreshClam remains enabled.

### Results

- Image: `sitara-clamav:1.5.4-ubuntu24.04`,
  image ID `sha256:6da7220499df7c914a05bfde7168c79e4f85b64ca28ab96e071fbb398d3e3c68`.
- Docker Scout against the rebuilt local image: **0 CRITICAL, 0 HIGH, 0
  MEDIUM, 0 LOW** across 192 packages; CVE-2026-86140 absent.
  Re-scan command: `docker scout cves --only-severity critical,high --exit-code local://sitara-clamav:1.5.4-ubuntu24.04`.
- Runtime: non-root `clamav` UID/GID 100:101; only `3310/tcp` exposed, no host
  port binding; `ldd` resolves `libxml2.so.2`; daemon returned `PONG`.
- FreshClam downloaded/verified the signature database. `clamdscan --version`
  and `sigtool --info daily.cvd` both reported signature version `28169`.
- Disposable daemon E2E: worker outage kept safe evidence `PENDING`; the same
  worker recovered; safe evidence became `CLEAN`, EICAR became `REJECTED`, and
  both scanned SHA-256 values matched. Worker/API tests: 14 passed; daemon
  scenario: 1 passed.
- HTTP Uvicorn E2E: backend suite 154 passed, 23 PostgreSQL-only tests skipped
  because no `SITARA_TEST_DATABASE_URL` was supplied; HTTP upload scenario
  passed and confirmed `http-safe.pdf|CLEAN|true`.
- Final local backend regression suite: 159 passed, 18 skipped, 5 warnings;
  configured coverage gate passed at 85.23%.
- `docker compose config --quiet` passed with `.env.example` explicitly
  selected. The existing project container and volumes were not recreated or
  removed; E2E used the isolated `sitara-stage6b-test` Compose project.

### Remaining risks and release operation

The package snapshot and base digest are intentionally frozen for repeatable
builds. Security updates require a reviewed digest/snapshot/package update,
rebuild, E2E run, and fresh Scout scan. Signature freshness is not currently a
healthcheck metric and must be monitored operationally.

## Stage 7 controlled rollout (2026-10-31)

The main Compose `clamav` service was recreated by itself with the verified
local image (`--no-deps --force-recreate --no-build`). The existing
`sitara_merged_workspace_sitara_clamav_database` volume was retained. Its
directory and signature files were read-only checked before rollout: UID/GID
100:101, directory mode 2755, files mode 644. The new container is healthy,
runs as UID/GID 100:101, has no published host port, and still exposes only
internal TCP 3310. `freshclam` and `clamd` are running; `clamdscan --ping=3`
returned PONG and both the daemon and `daily.cld` reported signature version
28169. A disposable peer on the Compose network also reached `clamav:3310` and
received PONG.

The main PostgreSQL container was already stopped before rollout; no API or
scanner-worker containers existed. They were left untouched, so this rollout
does not claim those services are live. Compose still configures the worker to
connect to `clamav:3310`. No database migration was run.

Post-rollout verification: worker tests 12 passed; disposable daemon E2E
reported 14 supporting tests passed and the outage/recovery scenario passed
(safe evidence stayed `PENDING` during outage, then became `CLEAN`; EICAR became
`REJECTED`; checksums matched). The full backend suite passed 159 tests, skipped
18, and passed the 85.23% coverage gate. Docker Scout again reported 0
CRITICAL/HIGH findings across 192 packages; Compose validation and
`git diff --check` passed.

The HTTP Uvicorn E2E was not rerun: its current cleanup explicitly removes its
disposable Docker evidence volume, which this rollout task prohibited. That
test passed during Stage 6B, but this is not a Stage 7 HTTP-E2E result. Rerun it
only with a cleanup path that does not remove a volume or after authorization
to remove that specifically disposable test volume.

## Stage 7.1 integration verification and safe HTTP E2E

### Environment audit

The main `sitara_merged_workspace-postgres-1` container was stopped with exit
code 0 and no Docker-reported error or OOM indication. The exact reason or actor
that stopped it could not be established. Main API and scanner-worker
containers were absent, rather than observed failing during startup. They were
not started, and no migration was run against the main database.

The main ClamAV container remained healthy on
`sitara-clamav:1.5.4-ubuntu24.04`, running as `clamav` (UID/GID 100:101), with
no published host port. The main PostgreSQL and ClamAV volumes remained
present. Other stopped containers and networks from prior test projects were
left untouched.

### Disposable runner safeguards

`backend/scripts/test-clamav-http-uvicorn-e2e.ps1` now creates a project name
from a UTC timestamp and full GUID, and uses that unique identity for its
container, internal network, evidence volume, and test-runner container.
Disposable Compose resources carry project ownership labels. Preflight rejects
resource-name collisions and verifies that the selected ClamAV container is
the expected healthy, non-root, unpublished main service and that daemon and
signature-file versions agree. The runner uses `.env.example` plus generated
synthetic test values; it does not read `.env`.

The test database uses container `tmpfs`; evidence uses a dedicated 64 MiB
`tmpfs` Docker volume. Cleanup targets only the generated Compose project and
exact resource names. Before removal, it checks ownership labels; the evidence
volume must also have the expected `tmpfs` options and be unused, and the
network must be internal with no unowned endpoints. Compose cleanup does not
use `down -v`. The main ClamAV container is temporarily attached to the
disposable internal test network and disconnected during guarded cleanup.
Cleanup runs from `finally` on success or failure and reports cleanup errors
instead of silently treating them as success. A regression test checks the
runner's scoped-cleanup safeguards. The completed run left no HTTP E2E
containers, test volume, or test network.

### HTTP E2E and integration results

The dedicated HTTP Uvicorn E2E passed: **1 passed, 1 warning**. It used
disposable PostgreSQL and evidence storage and verified:

- A safe PDF upload began `PENDING`, was scanned by the Compose worker, and
  became `CLEAN`.
- An EICAR upload began `PENDING` and became `REJECTED`.
- SHA-256 values matched for both scanned files.
- Downloads were denied while scans were pending and for rejected content;
  authorized download of the clean file returned the original bytes.
- Unauthenticated access returned `401`, and cross-task access was denied
  (`404`). The response did not expose a storage key.

Disposable PostgreSQL confirmed
`http-safe.pdf|CLEAN|true` and `http-eicar.txt|REJECTED|true`.

Within this isolated test project, API and scanner used the same disposable
database and evidence volume (API read/write; scanner read-only), and the
scanner reached the main ClamAV daemon as `clamav:3310` over the disposable
internal network. This verifies the disposable integration path only. The main
API, worker, and PostgreSQL were not running, so their live connectivity,
shared storage/database, and status updates remain **NOT VERIFIED**.

### Regression and quality checks

- Host backend suite: **160 passed, 18 skipped, 5 warnings**; the configured
  coverage threshold passed at **85.23%**. PostgreSQL-only concurrency tests
  could not run without `SITARA_TEST_DATABASE_URL`; dedicated harness tests
  were run separately where applicable. One symlink test was skipped because
  Windows did not grant the required symlink privilege.
- In the isolated E2E test-runner container, the supporting backend suite
  reported **155 passed, 23 skipped, 5 warnings**. Skips included PostgreSQL
  tests without a test database URL, Compose checks because the test container
  has no Docker CLI, and harness-marked tests run separately by the runner.
- The dedicated HTTP E2E scenario passed as reported above.
- Focused worker, storage, authorization, and runner checks: **60 passed,
  3 skipped, 2 warnings**.
- `ruff check .`, `ruff format --check app tests`, and `mypy app` passed.
- Main and disposable Compose configuration validation passed with
  `.env.example` and synthetic E2E values. PowerShell runner syntax validation
  and `git diff --check` passed.
- Docker Scout was not rerun for Stage 7.1. The last observed scan, during
  Stage 7, reported 0 Critical, 0 High, 0 Medium, and 0 Low findings for the
  pinned ClamAV image.

**Stage 7.1 status:** the safe disposable HTTP journey and disposable
API/worker/ClamAV path passed. Final live integration verification is
**NOT VERIFIED** until the main PostgreSQL, API, and worker can be safely
started and checked without changing production configuration or data. The
reason the main PostgreSQL container stopped also remains unknown.

## Stage 7.2 PostgreSQL recovery and live integration (2026-10-31)

### PostgreSQL shutdown investigation and recovery

Preflight reconfirmed branch `feat/integrate-clamav-worker` at
`b47d4125c3007653fc8d9e8c3ed9c2b4950dd67e`. The stopped
`sitara_merged_workspace-postgres-1` container used the existing
`postgres:16-alpine` image (PostgreSQL 16.15, image ID
`sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`)
and the expected Compose-owned
`sitara_merged_workspace_sitara_postgres_data` volume mounted read/write at
`/var/lib/postgresql/data`. Its exit code was 0, `OOMKilled` was false, and
Docker reported no container error. The data directory was owned by UID/GID
70:70 with mode 0700 and contained PostgreSQL data format version 16.

The final PostgreSQL log records a fast shutdown request, completed shutdown
checkpoint, and `database system is shut down`. Windows System event 1074
records a host power-off 13 seconds after that shutdown. This makes an
orderly stop around host shutdown the best-supported explanation, but neither
the Docker event log nor PostgreSQL identifies which actor sent the stop
signal. Exact cause: **NOT VERIFIED**. The subsequent startup reported the
previous clean shutdown time and became ready without recovery or permission
errors.

Only the existing PostgreSQL service/container was started with Compose
`start`; it was not recreated. It became healthy, and `pg_isready` accepted
connections. A read-only SQL transaction confirmed database `sitara_dev`,
role `sitara_app`, and five public tables: `alembic_version`, `roles`,
`user_roles`, `user_sessions`, and `users`. No migration was applied.

### API and worker startup gate

The database's recorded migration is `0001_identity_sessions`; the current
repository migration head is `0011_evidence_scan_quarantine`. The database
does not contain `action_items`, `action_item_evidence`, or
`action_item_evidence_scans`, which the current API/worker need. The expected
main named evidence volume `sitara_merged_workspace_sitara_action_item_evidence`
is also absent. Although the `sitara-backend:local` image is available, no
main API or scanner-worker container exists.

The API health route only reports process health; it does not check database
readiness. Starting the API would not establish working application/database
integration, and Compose would create the missing evidence volume. Starting
the worker against this schema would repeatedly fail its evidence query.
Accordingly neither service was created or started. No migration, volume
creation, API request, or evidence write was performed.

Live integration upload/scan/download: **NOT VERIFIED**, intentionally
blocked until the owner authorizes a reviewed schema upgrade path and the
expected evidence storage is provisioned/backed up. The Stage 7.1 disposable
HTTP E2E remains the latest successful end-to-end integration evidence.

### Regression, runtime state, and risks

- Backend regression: **160 passed, 18 skipped, 5 warnings**, coverage
  **85.23%**. Fifteen PostgreSQL concurrency tests skipped because
  `SITARA_TEST_DATABASE_URL` was not configured; two dedicated ClamAV/Uvicorn
  harness tests are run separately; one symlink test skipped because Windows
  denied symlink privilege.
- `ruff check .`, `ruff format --check app tests`, and `mypy app` passed.
- Main and disposable Compose validation using `.env.example` and synthetic
  E2E values passed. `git diff --check` passed.
- Main PostgreSQL is healthy on its original volume and unchanged PostgreSQL
  16 image. Main ClamAV remains healthy on
  `sitara-clamav:1.5.4-ubuntu24.04`, with its existing signature volume.
  API and worker remain absent; no disposable resources were created.
- The Compose PostgreSQL port is published on all host interfaces at 5432.
  This pre-existing exposure was not changed; restrict it to loopback or a
  trusted network if this is not intended for the local development host.
- No `.env` was read or changed. No commit, push, database migration, or
  volume removal occurred. Existing unrelated dirty worktree changes remain.

**Stage 7.2 status:** PostgreSQL recovery **PASS**; orderly shutdown around
host power-off is supported but the exact stop initiator is **NOT VERIFIED**.
API/worker live verification and live evidence journey are **NOT VERIFIED**
because the main database is far behind the application migration head and
the evidence volume is absent. Do not treat the full integration as release
ready.

## Stage 7.3 database migration assessment (current assessment)

The main PostgreSQL service was rechecked healthy on its original
`postgres:16-alpine` image and `sitara_merged_workspace_sitara_postgres_data`
volume. Its revision remains `0001_identity_sessions` (five public tables,
five seeded roles, and no users, assignments, or sessions); repository head
is `0011_evidence_scan_quarantine`. The expected schema gap is documented in
[`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md). No main migration/downgrade,
database reset, API/worker start, volume creation/removal, commit, or push was
performed. `.env` was not read or changed.

A temporary 8,204-byte custom-format `pg_dump` was restored successfully to
PostgreSQL 16 using a tmpfs-only disposable database. The restored copy
upgraded to `0011`, passed `alembic check` with no detected metadata drift,
and completed a disposable-only downgrade to `0001` followed by re-upgrade.
The temporary archive and scratch resources were removed; this does not
provide a retained or off-device operational backup. No pre-existing file
evidence existed in the restore source, so the `0011` file-row backfill was
not exercised with positive rows.

The focused PostgreSQL concurrency suite passed **15 tests**. The full backend
suite passed **175 tests, skipped 3**, with **5 warnings** and **85.66%**
coverage. The skips were the daemon and HTTP Compose harness tests (not enabled
in the full-suite run) and a symlink case unavailable under current Windows
permissions. Ruff lint/format checks, mypy, main/E2E Compose configuration,
and `git diff --check` passed.

The main evidence volume `sitara_merged_workspace_sitara_action_item_evidence`
is still absent. The API and scanner remain unstarted; live integration is
**NOT VERIFIED**. PostgreSQL's existing host port is bound to all interfaces
(`0.0.0.0` and `::`); this was not changed and should be restricted to loopback
or a trusted network if broad host exposure is unintended. Keep the API/worker
startup blocked until the migration is explicitly approved, the exact backup
is retained and restore-tested, and evidence storage ownership/permissions
are provisioned and verified. Do not scale the scanner above one replica.

## Local startup and one-time migration

1. Copy `.env.example` to `.env` and set local development values. Keep
   `DATABASE_URL_CONTAINER` pointed at `postgres:5432` in this Compose project,
   and make its database, username, and password match the `POSTGRES_*` values.
   Do not point this local migration procedure at a production database.
2. Start the local database and scanner daemon and wait for their healthchecks:

   ```powershell
   docker compose up -d --build --wait postgres clamav
   ```

3. Review the selected Compose database configuration, then apply the existing
   Alembic migrations once:

   ```powershell
   docker compose run --rm --no-deps api alembic upgrade head
   ```

4. Start the API and the single scanner worker:

   ```powershell
   docker compose up -d --wait api evidence-scanner
   ```

API and worker startup do not run migrations automatically. The worker should
not be scaled above one replica. Do not use `docker compose down -v` for routine
shutdown because it deletes the project's persistent database and evidence
volumes.

`DATABASE_URL` in `.env.example` remains for running the API directly on the
host; Compose services use `DATABASE_URL_CONTAINER`, whose PostgreSQL hostname
is `postgres`. The `CLAMAV_HOST=127.0.0.1` example is for host-run development;
Compose explicitly sets the worker's host to the internal service name `clamav`.

## Stage 7.4 — Backup readiness and evidence storage rehearsal (2026-10-31)

The main database remains healthy on its original PostgreSQL 16 container and
volume at Alembic revision `0001_identity_sessions`; the repository still
requires `0011_evidence_scan_quarantine`. The main evidence named volume is
absent. No main migration/downgrade, API/worker start, main-volume change,
commit, or push occurred, and `.env` was not read or changed.

A temporary 8,204-byte custom-format PostgreSQL archive was validated by
`pg_restore --list` and restored into a separate PostgreSQL 16 tmpfs-only
container with no Docker volume mounts. The restored Alembic revision,
five-table schema inventory (columns, constraints, and indexes), and
non-sensitive row counts matched the main database. The archive and disposable
resources were removed. This is a **PASS for the disposable backup/restore
rehearsal only**; there is no retained encrypted or off-device operational
backup, so durable backup readiness remains **NOT VERIFIED**.

A separate uniquely labeled disposable standard named-volume rehearsal at
`/var/lib/sitara/evidence` verified first-mount ownership/mode
`10001:10001`/`0700`, storage-service write as the non-root API identity,
file mode `0600`, archive/restore SHA-256 equality, and scanner-style
read-only access (read succeeded, write was denied). The exact synthetic file
and test volumes were removed after verification.

The API and scanner use the shared volume with read/write and read-only mounts,
respectively. ClamAV does not mount evidence files: the worker reads from its
mount and streams bytes to `clamav:3310` using INSTREAM. The main evidence
volume is still absent, and the main database at revision 0001 has no evidence
metadata or scan-history tables. Consequently real database/file recovery,
including preservation of `PENDING`, `CLEAN`, and `REJECTED` metadata, remains
**NOT VERIFIED**.

Before Stage 7.5, retain an encrypted PostgreSQL backup outside the database
volume and host/account failure domain, validate that exact backup by restoring
it to disposable PostgreSQL 16, provision the exact evidence volume only
after explicit approval, and verify a coordinated database/file restore.
Keep API and worker startup blocked until the main schema reaches migration
head, storage permissions are verified, API/worker dependencies are reviewed,
and ClamAV reachability is checked. Keep one scanner replica. The detailed
procedure, permission matrix, and startup checklist are in
[`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md).

## Stage 7.4.1 — Operational backup readiness (2026-10-31)

**Status: BLOCKED.** Stage 7.4's temporary PostgreSQL and synthetic evidence
archives were removed after local disposable restores. They were not
encrypted, retained, or copied off-device.

The Stage 7.4.1 shell preflight could not execute because the sandbox denied
local-proxy access. Available host drives, encryption tools, current Docker
state, and destination failure domain are therefore **NOT VERIFIED** in this
stage. No external destination was contacted, no operational archive was
created, and no key or secret was read or written. Refer to the Stage 7.4
baseline above as historical, not as a current Docker observation.

Operational readiness requires an approved destination on a separate host or
account failure domain, a maintained encryption mechanism with separately
controlled key custody, restricted access, an approved retention/legal-hold
policy, and successful restore testing from the exact encrypted off-device
archives. A local second folder, partition, Docker volume, or disk on the
primary host does not meet the off-device requirement. Until retention is
approved, automated pruning must remain disabled.

Database and evidence backup must describe one recovery point: pause uploads
and scanner result writes; create a binary-safe custom-format `pg_dump`;
archive the entire private evidence root from a read-only mount without
filtering on scan status; encrypt and transfer both to the approved
destination; then verify archive hashes and record a non-sensitive manifest.
Restore both to isolated, uniquely labeled disposable resources and compare
the Alembic revision, schema, status counts, metadata-to-file mapping, sizes,
and SHA-256 values. Preserve PENDING quarantine and REJECTED denial; never
reconstruct scan status from files.

The Stage 7.4 database restore and synthetic evidence-volume restore were
separate rehearsals, not a joint recovery-point test. The main database was
at revision `0001_identity_sessions` and the main evidence volume was absent,
so no real evidence metadata or files were available for coordinated
verification. That requirement remains **NOT VERIFIED**.

**Stage 7.4.1 is not ready. Stage 7.5 remains WAITING FOR APPROVAL.** Do not
migrate the main database, provision its evidence volume, or start the main
API/worker until an encrypted off-device backup and restore rehearsal of that
exact backup are verified and the remaining startup gates are approved.

## Stage 7.4.12 — Evidence backup specification

The current file-evidence implementation uses an opaque 32-character
hexadecimal storage key and stores the original filename, MIME type, size, and
SHA-256 in PostgreSQL. The private storage helper rejects invalid keys and
symlinks, confines files to the configured root, writes atomically, and uses
private directory/file modes. Scan state is append-only event history:
`PENDING`, `CLEAN`, or `REJECTED`; downloads require the latest `CLEAN` result
to match both the database digest and the file bytes/size.

A future recovery point must capture the PostgreSQL archive and complete
evidence root while upload and scanner-result writers are quiesced. Include
file bytes and all scan-history metadata regardless of status; do not make
PENDING files available, turn REJECTED into CLEAN, or infer state from the
filesystem. On restore, reconcile every FILE metadata row with exactly one
regular file and verify size and SHA-256. Report missing/orphan files and
mismatches without automatic deletion or status changes. LINK evidence is
external URL metadata; its target content is not included in the SITARA
evidence archive.

The latest main-environment check still found no evidence tables or named
evidence volume, and main API/worker were absent. This is a specification,
not proof that an operational evidence backup exists. The external HDD is the
planned priority offline medium; campus Microsoft 365 OneDrive is a fallback/
last resort with restricted folder access and manual ciphertext-only upload.
A dedicated SharePoint library is unavailable and no Entra application for
Graph has been provided. HDD availability/capacity and campus retention,
capacity, and recovery policies remain unverified; neither medium is
production-approved by this note. The key-custody, package, restore, and
readiness specification is maintained in [`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md).
No backup or transfer was performed for Stage 7.4.12 or this policy alignment.

## Stage 7.5 — Disposable E2E isolation

Both ClamAV E2E runners build invocation-specific backend, ClamAV, and
test-runner image tags. The daemon E2E uses a uniquely labeled disposable
ClamAV container, an internal test network, a separate temporary egress
network for FreshClam initialization, and a tmpfs signature directory whose
ownership is derived from the image's non-root `clamav` account. It detaches
egress before running the worker/outage/recovery scenario. PostgreSQL and
evidence/control paths remain disposable and use tmpfs; no ports are published.

The HTTP/Uvicorn E2E uses `docker-compose.e2e.yml`, a unique Compose project,
explicitly labeled external test networks, a tmpfs evidence volume, and unique
image tags. Only the disposable ClamAV container receives temporary egress for
signature initialization; the harness disconnects that network before API and
worker testing. The ClamAV tmpfs owner is also derived from the built image.
Neither harness references the main Compose project or its backend image tag.

Cleanup is scoped to the invocation's unique names and ownership labels. Before
removing containers, networks, volumes, or images, the runners verify their
identity and ownership; networks must be empty and evidence storage unused.
They do not run global pruning or remove shared project resources. If ownership
or identity checks fail, cleanup stops and reports the leftover resource.

The initial Stage 7.5 implementation check (before Stage 7.5.1) parsed both
PowerShell scripts and passed 13 focused Compose/runtime tests. Docker Desktop
Linux Engine was unavailable for that initial run, so neither E2E was started
then. That initial attempt was not an E2E result and was superseded by the
runtime verification below.

## Stage 7.5.1 — E2E runtime verification

**Historical result: PASS, as reported at Stage 7.5.1.** The disposable daemon
E2E verified signature database/daemon consistency, scanner outage preserving
`PENDING`, recovery by the same worker, a safe file becoming `CLEAN`, EICAR
becoming `REJECTED`, and matching evidence checksums. The HTTP/Uvicorn E2E
reported successful API, worker, and evidence lifecycle verification, with
safe and EICAR evidence reaching `CLEAN` and `REJECTED` respectively.
Ownership regression tests passed. Both harnesses reported successful
ownership-verified cleanup, and the main SITARA/smoke-stack resource
inventories were reported unchanged before and after each run.

These are Stage 7.5.1 results, not tests run while writing this record.

## Stage 7.5.2 — Final code review and pre-commit audit

The Stage 7.5.2 audit did **not** rerun either E2E. It reported a read-only
code review and these test/check results: backend suite **167 passed, 18
skipped, 5 warnings** with **85.23% coverage**; Compose/runtime tests **16
passed**; Ruff, changed-Python-file format check, mypy, PowerShell parser, and
`git diff --check` passed. Gitleaks reported no findings in the changed paths
it scanned, and `pip-audit` reported no known vulnerabilities. Docker Scout
was not run in that audit. The review identified a mismatch where Compose
allowed a configurable worker port while the daemon remained fixed at 3310;
that finding is addressed by the subsequent Stage 7.5.3 implementation and
tests, not by the Stage 7.5.2 audit.

## Stage 7.5.3 — ClamAV port consistency

**Historical result: PASS, as reported at Stage 7.5.3.** The daemon,
evidence-scanner, and TCP PING/PONG healthcheck now use the same validated
`CLAMAV_PORT`, defaulting to `3310`; invalid values fail explicitly. Regression
coverage includes the default, custom, and invalid-port cases. The focused
custom-port smoke test used port `3311` and its disposable resources were
reported cleaned up.

The stage reported **61 focused tests passed** and a backend suite of
**176 passed, 18 skipped, 5 warnings**, with **85.23% coverage**. Ruff lint,
changed-Python-file format checks, `mypy app`, PowerShell/Bash parsing, Compose
validation, and `git diff --check` were reported passing. These results belong
to Stage 7.5.3 and are not a verification run by later stages.

## Stage 7.5.4 — Final pre-commit review

The review found that the implicit main Compose network allowed the scanner
worker to reach services beyond its requirements. It recommended explicit
least-privilege networks; no E2E was rerun during that audit.

## Stage 7.5.5 — Docker network segmentation

**Historical result: PASS, as reported at Stage 7.5.5.** Main Compose assigns
the API to `api-db`, PostgreSQL to `api-db` and `scanner-db`, the worker to
`scanner-db` and `scanner`, and ClamAV to `scanner` and `clamav-egress`.
Database/scanner networks are internal; only ClamAV joins the egress-capable
network for FreshClam. The E2E topology mirrors these service boundaries.
ClamAV has no host-published port. Both E2E runners assert the live container
network attachments and use ownership-checked disposable resources.

The final daemon E2E reported **14 supporting worker/API tests passed** and
**1 daemon scenario passed**: outage kept evidence `PENDING`, the same worker
recovered, safe evidence became `CLEAN`, EICAR became `REJECTED`, and checksums
matched. The HTTP/Uvicorn E2E reported a full backend suite of **166 passed,
32 skipped, 5 warnings**, with **85.49% coverage**, followed by **1 HTTP
scenario passed**. It verified upload quarantine, `CLEAN`/`REJECTED` outcomes,
and matching checksums. Both runners reported cleanup of their disposable
containers, tmpfs-backed data, images, and networks. These are Stage 7.5.5
results, not tests rerun by this documentation update.

The Stage 7.5.5 code-quality report recorded `ruff check .`, changed-Python-
file format checks, `mypy app`, main/E2E Compose validation, PowerShell/Bash
parsing, and `git diff --check` as passing. Repository-wide
`ruff format --check .` still flags the unchanged
`migrations/versions/0003_meeting_workflow_login_rate_limit.py`, a baseline
exception also recorded in the test strategy. An initial HTTP harness attempt
failed before worker startup; the harness was corrected to start only the
already-validated worker and the final HTTP E2E passed as described above.

## Stage 7.5.6 — Final commit-readiness verification

The later read-only audit rendered main and E2E Compose configurations and
confirmed their expected network attachments, internal networks, and absence
of ClamAV host-port publishing. It reported **27 Compose regression tests
passed**, Ruff lint, changed-file Ruff format, `mypy app`, PowerShell/Bash
parsing, `git diff --check`, and a redacted changed-file Gitleaks scan as
passing. It did not rerun the full backend suite or either E2E. Docker Engine
was unavailable to that audit, so it did not freshly verify live runtime
attachments or main-container health. The successful Stage 7.5.5 runtime
results above remain historical evidence, not a Stage 7.5.6 runtime result.
