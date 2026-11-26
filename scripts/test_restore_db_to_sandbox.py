import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/restore-db-to-sandbox.sh"
CONTAINER_ID = "a" * 64
NETWORK_ID = "b" * 64
SYSTEM_IDENTIFIER = "1234567890123456789"
ARCHIVE_BYTES = b"synthetic archive bytes"
SHA256 = hashlib.sha256(ARCHIVE_BYTES).hexdigest()


DOCKER_STUB = r"""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$MOCK_LOG"
case "$1" in
  inspect)
    if [[ "$*" == *"NetworkSettings.Ports"* ]]; then
      printf '%s|%s|postgres:16-alpine|%s|%s|%s|%s|%s|%s|%s\n' \
          "$MOCK_CONTAINER_ID" "$MOCK_CONTAINER_RUNNING" "$MOCK_DISPOSABLE_LABEL" "$MOCK_RUN_LABEL" \
        "$MOCK_COMPOSE_PROJECT" "$MOCK_DATA_TMPFS" "$MOCK_TMPFS_COUNT" \
        "$MOCK_PERSISTENT_MOUNTS" "$MOCK_PUBLISHED_PORTS"
    elif [[ "$*" == *"NetworkSettings.Networks"* ]]; then
      printf '%s\n' "$MOCK_NETWORK_ID"
    else
      exit 2
    fi
    ;;
  network)
    printf '%s|%s|%s\n' "$MOCK_NETWORK_COUNT" "$MOCK_CONTAINER_ID" "$MOCK_NETWORK_ID"
    ;;
  exec)
    shift
    shift
    case "$*" in
      *"pg_restore --version"*)
        if [[ "$MOCK_SCENARIO" == "restore_tool_mismatch" ]]; then
          printf 'pg_restore (PostgreSQL) 15.15\n'
        else
          printf 'pg_restore (PostgreSQL) 16.15\n'
        fi
        ;;
      *"pg_restore --list"*)
        cat > "$MOCK_LIST_INPUT"
        if [[ "$MOCK_SCENARIO" == "corrupt_archive" ]]; then
          printf 'invalid archive\n' >&2
          exit 1
        fi
        if [[ "$MOCK_SCENARIO" == "mutate_source" ]]; then
          printf 'changed source after staging' > "$MOCK_ARCHIVE_PATH"
        fi
        printf '; Archive created at 2026-11-04\n;     dbname: synthetic\n'
        if [[ "$MOCK_SCENARIO" == "archive_version_mismatch" ]]; then
          printf ';     Dumped from database version: 15.15\n'
        else
          printf ';     Dumped from database version: 16.15\n'
        fi
        printf '; Dumped by pg_dump version: 16.15\n'
        printf 'TABLE public synthetic\n'
        ;;
      *"pg_restore"*)
        cat > "$MOCK_RESTORE_INPUT"
        if [[ "$MOCK_SCENARIO" == "restore_failure" ]]; then
          printf 'synthetic restore failure\n' >&2
          exit 1
        fi
        ;;
      *"psql"*)
        if [[ "$MOCK_SCENARIO" == "target_connection_failure" ]]; then
          exit 1
        elif [[ "$*" == *"system_identifier"* ]]; then
          printf '%s\n' "$MOCK_SYSTEM_IDENTIFIER"
        elif [[ "$*" == *"server_version_num"* ]]; then
          printf '%s\n' "$MOCK_SERVER_VERSION"
        elif [[ "$*" == *"SHOW server_version"* ]]; then
          printf '16.15\n'
        elif [[ "$*" == *"SHOW port"* ]]; then
          printf '5432\n'
        elif [[ "$*" == *"SHOW data_directory"* ]]; then
          if [[ "$MOCK_SCENARIO" == "bad_data_directory" ]]; then
            printf '/var/lib/postgresql/other\n'
          else
            printf '/var/lib/postgresql/data\n'
          fi
        elif [[ "$*" == *"pg_database"* ]]; then
          if [[ "$*" == *"datistemplate"* && "$MOCK_SCENARIO" == "nonempty_cluster" ]]; then
            printf '1\n'
          elif [[ "$MOCK_SCENARIO" == "existing_database" ]]; then
            printf '1\n'
          else
            printf '0\n'
          fi
        elif [[ "$*" == *"CREATE DATABASE"* ]]; then
          printf 'CREATE DATABASE\n'
        elif [[ "$*" == *"information_schema.tables"* ]]; then
          printf '1\n'
        elif [[ "$*" == *"alembic_version"* ]]; then
          printf '0001_identity_sessions\n'
        elif [[ "$*" == *"pg_tables"* ]]; then
          printf '5\n'
        elif [[ "$*" == *"SELECT 1"* ]]; then
          printf '1\n'
        else
          exit 2
        fi
        ;;
      *)
        exit 2
        ;;
    esac
    ;;
  *)
    exit 2
    ;;
esac
"""

AGE_STUB = r"""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$MOCK_AGE_LOG"
if [[ "$1" != "--decrypt" || "$2" != "--identity" || "$4" != "--output" ]]; then
  exit 2
fi
output="$5"
input="$6"
if [[ "${MOCK_AGE_FAILURE:-}" == "decrypt" ||
  ( "${MOCK_AGE_FAILURE:-}" == "archive" && "$input" == *"database.dump.age" ) ||
  ( "${MOCK_AGE_FAILURE:-}" == "identity" && "$3" == "$MOCK_INVALID_IDENTITY" ) ]]; then
  exit 1
fi
if [[ ! -f "$input" ]]; then
  exit 2
fi
if ! IFS= read -r header < "$input" || [[ "$header" != "TEST-ONLY-ENCRYPTED" ]]; then
  exit 1
fi
tail -n +2 "$input" > "$output"
printf 'staged_mode=%s\n' "$(stat -c '%a' -- "$output")" >> "$MOCK_AGE_LOG"
"""


class RestoreScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.log = self.root / "external-commands.log"
        self.age_log = self.root / "age.log"
        self.archive = self.root / "synthetic.dump"
        self.archive.write_bytes(ARCHIVE_BYTES)
        self.report = self.root / "restore-report.txt"
        self._write_executable(self.bin_dir / "docker", DOCKER_STUB)
        self._write_executable(self.bin_dir / "age", AGE_STUB)
        self.identity = self.root / "synthetic-identity.txt"
        self.identity.write_text("synthetic identity fixture\n", encoding="ascii")
        self.identity.chmod(0o600)
        self.bundle = self.root / "encrypted-backup"
        self.bundle.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_executable(self, path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8", newline="\n")
        path.chmod(0o700)

    def _bash_path(self, path: Path) -> str:
        value = str(path.resolve())
        if len(value) >= 3 and value[1:3] == ":\\":
            suffix = value[2:].replace("\\", "/")
            return f"/{value[0].lower()}{suffix}"
        return value.replace("\\", "/")

    def _env(self, scenario: str = "success") -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": os.pathsep.join((str(self.bin_dir), env.get("PATH", ""))),
                "MOCK_LOG": str(self.log),
                "MOCK_AGE_LOG": str(self.age_log),
                "MOCK_ARCHIVE_PATH": str(self.archive),
                "MOCK_LIST_INPUT": str(self.root / "listed-archive.bin"),
                "MOCK_RESTORE_INPUT": str(self.root / "restored-archive.bin"),
                "MOCK_SCENARIO": scenario,
                "MOCK_CONTAINER_ID": CONTAINER_ID,
                "MOCK_CONTAINER_RUNNING": "true",
                "MOCK_NETWORK_ID": NETWORK_ID,
                "MOCK_NETWORK_COUNT": "1",
                "MOCK_DISPOSABLE_LABEL": "true",
                "MOCK_RUN_LABEL": "test_123",
                "MOCK_COMPOSE_PROJECT": "<no value>",
                "MOCK_DATA_TMPFS": "true",
                "MOCK_TMPFS_COUNT": "1",
                "MOCK_PERSISTENT_MOUNTS": "",
                "MOCK_PUBLISHED_PORTS": "",
                "MOCK_SYSTEM_IDENTIFIER": SYSTEM_IDENTIFIER,
                "MOCK_SERVER_VERSION": "160015",
                "SITARA_RESTORE_ENVIRONMENT": "disposable",
                "SITARA_RESTORE_CONTAINER_ID": CONTAINER_ID,
                "SITARA_RESTORE_TARGET_HOST": f"container:{CONTAINER_ID}",
                "SITARA_RESTORE_TARGET_PORT": "5432",
                "SITARA_RESTORE_RUN_ID": "test_123",
                "SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER": SYSTEM_IDENTIFIER,
                "SITARA_RESTORE_DB_USER": "restore_admin",
            }
        )
        return env

    def _run(
        self,
        target: str | None = "sitara_restore_test_123",
        *,
        scenario: str = "success",
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = ["bash", SCRIPT]
        if self.archive is not None:
            args.append(str(self.archive))
        if target is not None:
            args.append(target)
            args.append(str(self.report))
        return subprocess.run(
            args,
            cwd=ROOT,
            env=env or self._env(scenario),
            capture_output=True,
            text=True,
            check=False,
        )

    def _calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def _write_ciphertext(self, path: Path, plaintext: bytes) -> None:
        path.write_bytes(b"TEST-ONLY-ENCRYPTED\n" + plaintext)
        path.chmod(0o600)

    def _write_checksum(self, path: Path) -> None:
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        Path(f"{path}.sha256").write_text(
            f"{checksum}  {path.name}\n",
            encoding="ascii",
        )

    def _create_encrypted_bundle(
        self,
        *,
        archive: bytes = ARCHIVE_BYTES,
        plaintext_digest: str | None = None,
    ) -> Path:
        archive_path = self.bundle / "database.dump.age"
        manifest_path = self.bundle / "manifest.json.age"
        self._write_ciphertext(archive_path, archive)
        manifest = {
            "backup_id": "sitara-backup-synthetic-test",
            "status": "COMPLETE",
            "source_environment": "synthetic-test",
            "source_database": "synthetic_fixture",
            "archive_format": "custom",
            "plaintext_archive_size_bytes": len(archive),
            "plaintext_archive_sha256": plaintext_digest
            or hashlib.sha256(archive).hexdigest(),
            "encrypted_file": "database.dump.age",
            "encrypted_file_size_bytes": archive_path.stat().st_size,
            "encrypted_file_sha256": hashlib.sha256(
                archive_path.read_bytes()
            ).hexdigest(),
            "encryption": "age",
            "age_version": "test-stub",
        }
        self._write_ciphertext(
            manifest_path,
            json.dumps(manifest, separators=(",", ":")).encode("utf-8"),
        )
        self._write_checksum(archive_path)
        self._write_checksum(manifest_path)
        return self.bundle

    def _run_encrypted(
        self,
        *,
        scenario: str = "success",
        age_failure: str | None = None,
        cleanup_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if not (self.bundle / "database.dump.age").exists():
            self._create_encrypted_bundle()
        args = [
            "bash",
            SCRIPT,
            "--encrypted",
            str(self.bundle),
            str(self.identity),
            "sitara_restore_test_123",
            str(self.report),
        ]
        env = self._env(scenario)
        temp_root = self.root / "private-tmp"
        temp_root.mkdir(exist_ok=True)
        env["TMPDIR"] = self._bash_path(temp_root)
        invalid_identity = self.root / "invalid-identity.txt"
        invalid_identity.write_text("invalid synthetic identity\n", encoding="ascii")
        invalid_identity.chmod(0o600)
        env["MOCK_INVALID_IDENTITY"] = str(invalid_identity)
        if age_failure:
            env["MOCK_AGE_FAILURE"] = age_failure
            if age_failure == "identity":
                args[4] = str(invalid_identity)
        if cleanup_failure:
            env["BASH_ENV"] = str(self.root / "bash-env.sh")
            Path(env["BASH_ENV"]).write_text(
                'rm() { if [[ "${MOCK_TEMP_CLEANUP_FAIL:-0}" == "1" '
                '&& "$1" == "-rf" && "$2" == "--" '
                '&& "$3" == "$MOCK_TEMP_ROOT"/* ]]; '
                'then return 1; fi; command rm "$@"; }\n',
                encoding="ascii",
            )
            env["BASH_ENV"] = self._bash_path(Path(env["BASH_ENV"]))
            env["MOCK_TEMP_CLEANUP_FAIL"] = "1"
            env["MOCK_TEMP_ROOT"] = self._bash_path(temp_root)
        return subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _reset_attempt(self) -> None:
        for path in (
            self.report,
            self.log,
            self.age_log,
            self.root / "listed-archive.bin",
            self.root / "restored-archive.bin",
        ):
            path.unlink(missing_ok=True)
        for path in self.bundle.iterdir():
            path.unlink()

    def test_target_database_is_required_and_no_default_is_used(self) -> None:
        result = self._run(target=None)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

    def test_database_name_must_match_unique_run_id(self) -> None:
        result = self._run(target="sitara_restore_other_run")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

    def test_primary_and_test_databases_are_rejected(self) -> None:
        for database in ("sitara_dev", "sitara_test"):
            with self.subTest(database=database):
                self._reset_attempt()
                result = self._run(target=database)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("protected", result.stderr.lower())
                self.assertEqual(self._calls(), "")

    def test_configured_production_database_is_rejected(self) -> None:
        env = self._env()
        env["SITARA_RESTORE_PROTECTED_DATABASES"] = "sitara_production"

        result = self._run(target="sitara_production", env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected", result.stderr.lower())
        self.assertEqual(self._calls(), "")

    def test_application_database_role_is_rejected(self) -> None:
        env = self._env()
        env["SITARA_RESTORE_DB_USER"] = "sitara_app"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

    def test_missing_cluster_identity_is_rejected_before_docker_access(self) -> None:
        env = self._env()
        env.pop("SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER")

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

    def test_environment_must_be_explicitly_disposable(self) -> None:
        env = self._env()
        env["SITARA_RESTORE_ENVIRONMENT"] = "development"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("inspect", self._calls())
        self.assertIn("status=FAILED", self.report.read_text(encoding="utf-8"))

    def test_compose_managed_cluster_is_rejected(self) -> None:
        env = self._env()
        env["MOCK_COMPOSE_PROJECT"] = "sitara_merged_workspace"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("pg_restore", self._calls())

    def test_container_without_disposable_label_is_rejected(self) -> None:
        env = self._env()
        env["MOCK_DISPOSABLE_LABEL"] = "false"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertNotIn("pg_restore", self._calls())

    def test_container_without_tmpfs_is_rejected(self) -> None:
        env = self._env()
        env["MOCK_DATA_TMPFS"] = "false"
        env["MOCK_TMPFS_COUNT"] = "0"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertNotIn("pg_restore", self._calls())

    def test_unsafe_container_identity_or_runtime_is_rejected_before_restore(self) -> None:
        unsafe_values = (
            ("MOCK_CONTAINER_ID", "c" * 64),
            ("MOCK_CONTAINER_RUNNING", "false"),
            ("MOCK_PERSISTENT_MOUNTS", "persistent,"),
            ("MOCK_PUBLISHED_PORTS", "published,"),
        )
        for key, value in unsafe_values:
            with self.subTest(key=key):
                self._reset_attempt()
                env = self._env()
                env[key] = value

                result = self._run(env=env)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "verified isolated PostgreSQL 16 disposable target",
                    result.stderr,
                )
                self.assertNotIn("CREATE DATABASE", self._calls())
                self.assertNotIn("pg_restore --exit-on-error", self._calls())

    def test_network_shared_with_another_container_is_rejected(self) -> None:
        env = self._env()
        env["MOCK_NETWORK_COUNT"] = "2"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("pg_restore", self._calls())

    def test_target_connection_failure_is_not_reported_as_success(self) -> None:
        result = self._run(scenario="target_connection_failure")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertNotIn("pg_restore --exit-on-error", self._calls())
        self.assertIn("status=FAILED", self.report.read_text(encoding="utf-8"))

    def test_unverified_postgres_system_identifier_is_rejected(self) -> None:
        env = self._env()
        env["SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER"] = "987654321"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())

    def test_non_tmpfs_data_directory_is_rejected(self) -> None:
        result = self._run(scenario="bad_data_directory")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())

    def test_invalid_host_or_port_is_rejected(self) -> None:
        for key, value in (
            ("SITARA_RESTORE_TARGET_HOST", "0.0.0.0"),
            ("SITARA_RESTORE_TARGET_PORT", "55432"),
        ):
            with self.subTest(key=key):
                self._reset_attempt()
                env = self._env()
                env[key] = value
                result = self._run(env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self._calls(), "")

    def test_existing_database_is_rejected_without_drop(self) -> None:
        result = self._run(scenario="existing_database")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertNotIn("dropdb", self._calls())

    def test_nonempty_disposable_cluster_is_rejected(self) -> None:
        result = self._run(scenario="nonempty_cluster")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertNotIn("pg_restore --exit-on-error", self._calls())

    def test_missing_empty_and_checksum_mismatch_archives_are_rejected(self) -> None:
        original = self.archive.read_bytes()
        self.archive.unlink()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

        self._reset_attempt()
        self.archive.write_bytes(b"")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._calls(), "")

        self._reset_attempt()
        self.archive.write_bytes(original)
        Path(f"{self.archive}.sha256").write_text(f"{'f' * 64}\n", encoding="ascii")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertEqual(self.archive.read_bytes(), original)

    def test_corrupt_archive_and_incompatible_postgres_version_are_rejected(self) -> None:
        original = self.archive.read_bytes()
        result = self._run(scenario="corrupt_archive")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertEqual(self.archive.read_bytes(), original)

        self._reset_attempt()
        result = self._run(scenario="archive_version_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertEqual(self.archive.read_bytes(), original)

        self._reset_attempt()
        result = self._run(scenario="restore_tool_mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())

        self._reset_attempt()
        env = self._env()
        env["MOCK_SERVER_VERSION"] = "150008"
        result = self._run(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CREATE DATABASE", self._calls())

    def test_disposable_new_database_restore_writes_success_report(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        self.assertIn("CREATE DATABASE", calls)
        self.assertIn("pg_restore", calls)
        self.assertNotIn("dropdb", calls)
        self.assertNotIn("compose exec", calls)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("status=PASS", report)
        self.assertIn("revision=0001_identity_sessions", report)
        self.assertIn("table_count=5", report)
        self.assertEqual(
            (self.root / "listed-archive.bin").read_bytes(),
            (self.root / "restored-archive.bin").read_bytes(),
        )

    def test_valid_checksum_is_recorded_in_report(self) -> None:
        Path(f"{self.archive}.sha256").write_text(f"{SHA256}\n", encoding="ascii")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "archive_checksum_status=VERIFIED",
            self.report.read_text(encoding="utf-8"),
        )

    def test_restore_uses_the_same_private_copy_that_was_format_validated(self) -> None:
        original = self.archive.read_bytes()
        result = self._run(scenario="mutate_source")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.archive.read_bytes(), original)
        self.assertEqual((self.root / "listed-archive.bin").read_bytes(), original)
        self.assertEqual((self.root / "restored-archive.bin").read_bytes(), original)

    def test_restore_failure_is_not_reported_as_success_and_secret_is_not_logged(self) -> None:
        original_archive = self.archive.read_bytes()
        env = self._env("restore_failure")
        env["PGPASSWORD"] = "synthetic-secret-must-not-be-logged"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("status=FAILED", report)
        self.assertNotIn("status=PASS", report)
        self.assertNotIn("synthetic-secret-must-not-be-logged", result.stdout + result.stderr)
        self.assertNotIn("synthetic-secret-must-not-be-logged", report)
        self.assertEqual(self.archive.read_bytes(), original_archive)
        self.assertIn("CREATE DATABASE", self._calls())
        self.assertNotIn("dropdb", self._calls().lower())

    def test_report_is_never_overwritten(self) -> None:
        self.report.write_text("preexisting report\n", encoding="utf-8")

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.report.read_text(encoding="utf-8"), "preexisting report\n")
        self.assertNotIn("CREATE DATABASE", self._calls())

    def test_encrypted_bundle_is_decrypted_validated_and_restored(self) -> None:
        result = self._run_encrypted()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "listed-archive.bin").read_bytes(),
            ARCHIVE_BYTES,
        )
        self.assertEqual(
            (self.root / "restored-archive.bin").read_bytes(),
            ARCHIVE_BYTES,
        )
        self.assertIn("pg_restore", self._calls())
        self.assertIn("--identity", self.age_log.read_text(encoding="utf-8"))
        self.assertIn("staged_mode=600", self.age_log.read_text(encoding="utf-8"))
        self.assertIn(
            "archive_checksum_status=VERIFIED",
            self.report.read_text(encoding="utf-8"),
        )
        self.assertEqual(list(self.bundle.glob("*.dump")), [])
        self.assertEqual(list((self.root / "private-tmp").iterdir()), [])
        self.assertNotIn("sitara_dev", self._calls())
        self.assertNotIn("sitara_test", self._calls())

    def test_encrypted_bundle_ciphertext_checksum_mismatch_is_rejected(self) -> None:
        if not (self.bundle / "database.dump.age").exists():
            self._create_encrypted_bundle()
        archive_checksum = self.bundle / "database.dump.age.sha256"
        archive_checksum.write_text(f"{'f' * 64}\n", encoding="ascii")

        result = self._run_encrypted()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Encrypted backup SHA-256", result.stderr)
        self.assertFalse(self.age_log.exists())
        self.assertNotIn("pg_restore", self._calls())

    def test_encrypted_manifest_checksum_mismatch_is_rejected(self) -> None:
        self._create_encrypted_bundle()
        checksum = self.bundle / "manifest.json.age.sha256"
        checksum.write_text(f"{'f' * 64}\n", encoding="ascii")

        result = self._run_encrypted()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Encrypted backup SHA-256", result.stderr)
        self.assertFalse(self.age_log.exists())
        self.assertNotIn("pg_restore", self._calls())

    def test_encrypted_bundle_decryption_failure_and_invalid_identity_fail_closed(
        self,
    ) -> None:
        for failure in ("decrypt", "archive", "identity"):
            with self.subTest(failure=failure):
                self._reset_attempt()
                result = self._run_encrypted(age_failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Could not decrypt encrypted", result.stderr)
                self.assertNotIn("pg_restore", self._calls())
                self.assertNotIn("CREATE DATABASE", self._calls())
                self.assertEqual(list((self.root / "private-tmp").iterdir()), [])

    def test_encrypted_bundle_plaintext_checksum_mismatch_is_rejected(self) -> None:
        self._create_encrypted_bundle(plaintext_digest="0" * 64)

        result = self._run_encrypted()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the manifest", result.stderr)
        self.assertNotIn("pg_restore", self._calls())
        self.assertEqual(list((self.root / "private-tmp").iterdir()), [])

    def test_encrypted_bundle_invalid_archive_is_rejected_before_database_creation(
        self,
    ) -> None:
        self._create_encrypted_bundle(archive=b"invalid synthetic archive")

        result = self._run_encrypted(scenario="corrupt_archive")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rejected the backup archive format", result.stderr)
        self.assertNotIn("CREATE DATABASE", self._calls())
        self.assertEqual(list((self.root / "private-tmp").iterdir()), [])

    def test_encrypted_restore_failure_cleans_private_plaintext_staging(self) -> None:
        result = self._run_encrypted(scenario="restore_failure")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status=FAILED", self.report.read_text(encoding="utf-8"))
        self.assertEqual(list((self.root / "private-tmp").iterdir()), [])
        self.assertEqual(list(self.bundle.glob("*.dump")), [])

    def test_encrypted_restore_cleanup_failure_is_reported_as_failure(self) -> None:
        result = self._run_encrypted(cleanup_failure=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not remove the private temporary directory", result.stderr)
        self.assertIn("status=FAILED", self.report.read_text(encoding="utf-8"))
        self.assertIn("error_code=TEMP_CLEANUP_FAILED", self.report.read_text(encoding="utf-8"))
        staged = list((self.root / "private-tmp").iterdir())
        self.assertEqual(len(staged), 1)
        self.assertTrue((staged[0] / "restore-input.dump").is_file())
        self.assertEqual(list(self.bundle.glob("*.dump")), [])

    def test_backup_script_artifact_is_accepted_by_encrypted_restore(self) -> None:
        from scripts.test_backup_db import BackupScriptTests

        backup_case = BackupScriptTests(
            "test_allowlisted_synthetic_source_produces_encrypted_archive_and_manifest"
        )
        backup_case.setUp()
        try:
            backup_result = backup_case._run()
            self.assertEqual(backup_result.returncode, 0, backup_result.stderr)
            packages = list(backup_case.destination.glob("sitara-backup-*"))
            self.assertEqual(len(packages), 1)
            for artifact in packages[0].iterdir():
                shutil.copy2(artifact, self.bundle / artifact.name)
            result = self._run_encrypted()
        finally:
            backup_case.tearDown()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "listed-archive.bin").read_bytes(),
            b"SYNTHETIC_CUSTOM_POSTGRESQL_ARCHIVE",
        )
        self.assertEqual(
            (self.root / "restored-archive.bin").read_bytes(),
            b"SYNTHETIC_CUSTOM_POSTGRESQL_ARCHIVE",
        )
        self.assertEqual(list(self.bundle.glob("*.dump")), [])
        self.assertEqual(list((self.root / "private-tmp").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
