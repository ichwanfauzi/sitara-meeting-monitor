import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/backup-db.sh"
CONTAINER_ID = "a" * 64
SYSTEM_IDENTIFIER = "1234567890123456789"
DATABASE = "synthetic_backup_fixture"
DATABASE_USER = "synthetic_backup_user"
RECIPIENT = "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
ARCHIVE = b"SYNTHETIC_CUSTOM_POSTGRESQL_ARCHIVE"


DOCKER_STUB = r"""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$MOCK_DOCKER_LOG"
case "$1" in
  inspect)
    printf '%s|%s\n' "$MOCK_CONTAINER_ID" "$MOCK_CONTAINER_RUNNING"
    ;;
  exec)
    shift
    if [[ "$1" == "-i" ]]; then shift; fi
    shift
    if [[ "$*" == *"--host=/var/run/postgresql"* && "${MSYS_NO_PATHCONV:-}" != "1" ]]; then
      printf 'container socket path was not protected from host path conversion\n' >&2
      exit 1
    fi
    case "$*" in
      *"pg_dump --version"*)
        if [[ "$MOCK_SCENARIO" == "client_version_mismatch" ]]; then
          printf 'pg_dump (PostgreSQL) 15.15\n'
        else
          printf 'pg_dump (PostgreSQL) 16.15\n'
        fi
        ;;
      *"pg_restore --version"*)
        printf 'pg_restore (PostgreSQL) 16.15\n'
        ;;
      *"psql --version"*)
        printf 'psql (PostgreSQL) 16.15\n'
        ;;
      *"pg_restore --list"*)
        cat > "$MOCK_ARCHIVE_LIST_INPUT"
        if [[ "$MOCK_SCENARIO" == "invalid_archive" ]]; then
          printf 'synthetic archive validation error\n' >&2
          exit 1
        fi
        printf '; Dumped from database version: 16.15\n'
        ;;
      *"pg_dump "*)
        if [[ "$MOCK_SCENARIO" == "pg_dump_failure" ]]; then
          printf 'partial archive bytes\n' >&2
          printf 'partial archive bytes'
          exit 1
        elif [[ "$MOCK_SCENARIO" == "empty_archive" ]]; then
          exit 0
        fi
        printf '%s' "$MOCK_ARCHIVE_CONTENT"
        ;;
      *"psql "*)
        if [[ "$MOCK_SCENARIO" == "connection_failure" ]]; then
          printf 'SYNTHETIC_SECRET_MARKER connection details\n' >&2
          exit 1
        elif [[ "$*" == *"pg_database_size"* ]]; then
          printf '1048576\n'
        elif [[ "$*" == *"current_database"* ]]; then
          if [[ "$MOCK_SCENARIO" == "database_mismatch" ]]; then
            printf 'other_fixture\n'
          else
            printf 'synthetic_backup_fixture\n'
          fi
        elif [[ "$*" == *"rolsuper"* ]]; then
          if [[ "$MOCK_SCENARIO" == "overprivileged_backup_role" ]]; then
            printf '1\n'
          else
            printf '0\n'
          fi
        elif [[ "$*" == *"system_identifier"* ]]; then
          printf '%s\n' "$MOCK_SYSTEM_IDENTIFIER"
        elif [[ "$*" == *"server_version_num"* ]]; then
          if [[ "$MOCK_SCENARIO" == "server_version_mismatch" ]]; then
            printf '150015\n'
          else
            printf '160015\n'
          fi
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
if [[ "$1" == "--version" ]]; then
  printf '1.2.0\n'
  exit 0
fi
if [[ "$1" == "--decrypt" ]]; then
  if [[ "$2" != "--identity" || "$4" != "--output" ]]; then
    exit 2
  fi
  output="$5"
  input="$6"
  if ! IFS= read -r header < "$input" || [[ "$header" != "TEST-ONLY-ENCRYPTED" ]]; then
    exit 1
  fi
  tail -n +2 "$input" > "$output"
  exit 0
fi
if [[ "$1" == "--encrypt" ]]; then
  current_count=0
  if [[ -f "$MOCK_AGE_COUNT" ]]; then
    current_count="$(cat "$MOCK_AGE_COUNT")"
  fi
  next_count=$((current_count + 1))
  printf '%s\n' "$next_count" > "$MOCK_AGE_COUNT"
  if [[ "${MOCK_AGE_FAIL_AT:-0}" == "$next_count" ]]; then
    printf 'SYNTHETIC_SECRET_MARKER age diagnostic\n' >&2
    exit 1
  fi
fi
if [[ "${MOCK_AGE_FAIL:-0}" == "1" ]]; then
  printf 'SYNTHETIC_SECRET_MARKER age diagnostic\n' >&2
  exit 1
fi
if [[ "$1" != "--encrypt" || "$2" != "--recipient" ]]; then
  exit 2
fi
shift 3
if [[ "$1" != "--output" ]]; then
  exit 2
fi
output="$2"
input="$3"
printf 'TEST-ONLY-ENCRYPTED\n' > "$output"
cat "$input" >> "$output"
"""


class BackupScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.destination = self.root / "private-backups"
        self.destination.mkdir(mode=0o700)
        self.docker_log = self.root / "docker.log"
        self.age_log = self.root / "age.log"
        self.age_count = self.root / "age.count"
        self.df_env = self.root / "bash-env.sh"
        self.df_env.write_text(
            'uname() { printf "%s\\n" "${MOCK_UNAME:-Linux}"; }\n'
            'stat() { if [[ "$1" == "-c" && "$2" == "%a" ]]; then printf "700\\n"; '
            'else command stat "$@"; fi; }\n'
            'mv() { if [[ "${MOCK_PUBLISH_FAIL:-0}" == "1" && "$1" == "-T" ]]; '
            'then return 0; fi; command mv "$@"; }\n'
            'rm() { if [[ "${MOCK_STAGING_CLEANUP_FAIL:-0}" == "1" && "$1" == "-rf" '
            '&& "$*" == *".sitara-backup-"* ]]; then return 1; fi; command rm "$@"; }\n'
            'df() { printf "Filesystem 1024-blocks Used Available Capacity Mounted on\\n'
            'synthetic 100000000 0 %s 0%% /synthetic\\n" "$MOCK_AVAILABLE_KB"; }\n',
            encoding="utf-8",
        )
        self._write_executable(self.bin_dir / "docker", DOCKER_STUB)
        self._write_executable(self.bin_dir / "age", AGE_STUB)

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
                "BASH_ENV": self._bash_path(self.df_env),
                "MOCK_DOCKER_LOG": self._bash_path(self.docker_log),
                "MOCK_AGE_LOG": self._bash_path(self.age_log),
                "MOCK_AGE_COUNT": self._bash_path(self.age_count),
                "MOCK_ARCHIVE_LIST_INPUT": self._bash_path(self.root / "archive-list.bin"),
                "MOCK_SCENARIO": scenario,
                "MOCK_ARCHIVE_CONTENT": ARCHIVE.decode("ascii"),
                "MOCK_CONTAINER_ID": CONTAINER_ID,
                "MOCK_CONTAINER_RUNNING": "true",
                "MOCK_SYSTEM_IDENTIFIER": SYSTEM_IDENTIFIER,
                "MOCK_AVAILABLE_KB": "100000000",
            }
        )
        return env

    def _args(
        self,
        *,
        database: str = DATABASE,
        destination: Path | str | None = None,
    ) -> list[str]:
        return [
            "bash",
            SCRIPT,
            "--container-id",
            CONTAINER_ID,
            "--expected-system-identifier",
            SYSTEM_IDENTIFIER,
            "--database",
            database,
            "--database-user",
            DATABASE_USER,
            "--environment",
            "synthetic-test",
            "--destination",
            (
                self._bash_path(Path(destination))
                if destination is not None
                else self._bash_path(self.destination)
            ),
            "--age-recipient",
            RECIPIENT,
            "--allow-database",
            DATABASE,
        ]

    def _run(
        self,
        *,
        database: str = DATABASE,
        scenario: str = "success",
        destination: Path | str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._args(database=database, destination=destination),
            cwd=ROOT,
            env=env or self._env(scenario),
            capture_output=True,
            text=True,
            check=False,
        )

    def _docker_calls(self) -> str:
        return self.docker_log.read_text(encoding="utf-8") if self.docker_log.exists() else ""

    def test_requires_an_explicit_source_and_destination(self) -> None:
        result = subprocess.run(
            ["bash", SCRIPT],
            cwd=ROOT,
            env=self._env(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._docker_calls(), "")
        self.assertFalse(any(self.destination.iterdir()))

    def test_allowlisted_synthetic_source_produces_encrypted_archive_and_manifest(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        packages = list(self.destination.glob("sitara-backup-*"))
        self.assertEqual(len(packages), 1)
        package = packages[0]
        encrypted = package / "database.dump.age"
        manifest_path = package / "manifest.json.age"
        checksum_path = package / "database.dump.age.sha256"
        manifest_checksum_path = package / "manifest.json.age.sha256"
        self.assertTrue(encrypted.is_file())
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(manifest_checksum_path.is_file())
        self.assertTrue(checksum_path.is_file())
        self.assertFalse((package / "database.dump").exists())
        self.assertFalse((package / "manifest.json").exists())

        manifest_bytes = manifest_path.read_bytes()
        self.assertTrue(manifest_bytes.startswith(b"TEST-ONLY-ENCRYPTED\n"))
        manifest = json.loads(manifest_bytes.partition(b"\n")[2].decode("utf-8"))
        encrypted_digest = hashlib.sha256(encrypted.read_bytes()).hexdigest()
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertEqual(manifest["source_database"], DATABASE)
        self.assertEqual(manifest["source_cluster_system_identifier"], SYSTEM_IDENTIFIER)
        self.assertEqual(manifest["archive_format"], "custom")
        self.assertEqual(manifest["encryption"], "age")
        self.assertEqual(manifest["encrypted_file_sha256"], encrypted_digest)
        self.assertIn(encrypted_digest, checksum_path.read_text(encoding="utf-8"))
        self.assertIn(manifest_digest, manifest_checksum_path.read_text(encoding="utf-8"))
        self.assertIn("--format=custom", self._docker_calls())

    def test_database_not_in_explicit_allowlist_is_rejected_before_docker(self) -> None:
        result = self._run(database="unapproved_fixture")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_NOT_ALLOWLISTED", result.stderr)
        self.assertEqual(self._docker_calls(), "")
        self.assertFalse(any(self.destination.iterdir()))

    def test_pg_dump_failure_does_not_publish_partial_backup(self) -> None:
        result = self._run(scenario="pg_dump_failure")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PG_DUMP_FAILED", result.stderr)
        self.assertIn("pg_dump", self._docker_calls())
        self.assertFalse(list(self.destination.glob("sitara-backup-*")))
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_source_container_identity_must_match_before_database_queries(self) -> None:
        env = self._env()
        env["MOCK_CONTAINER_ID"] = "b" * 64

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_CONTAINER_ID_MISMATCH", result.stderr)
        self.assertNotIn(" exec ", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_stopped_source_container_is_rejected_before_database_queries(self) -> None:
        env = self._env()
        env["MOCK_CONTAINER_RUNNING"] = "false"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_CONTAINER_NOT_RUNNING", result.stderr)
        self.assertNotIn(" exec ", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_source_cluster_identity_must_match_before_dump(self) -> None:
        env = self._env()
        env["MOCK_SYSTEM_IDENTIFIER"] = "9876543210987654321"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_SYSTEM_IDENTIFIER_MISMATCH", result.stderr)
        self.assertNotIn("pg_dump --username", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_postgresql_client_major_must_match_the_supported_server(self) -> None:
        result = self._run(scenario="client_version_mismatch")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("POSTGRESQL_CLIENT_VERSION_MISMATCH", result.stderr)
        self.assertNotIn("pg_dump --username", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_source_server_major_must_match_the_supported_restore_version(self) -> None:
        result = self._run(scenario="server_version_mismatch")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNSUPPORTED_POSTGRESQL_MAJOR", result.stderr)
        self.assertNotIn("pg_dump ", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_insufficient_destination_capacity_fails_before_source_access(self) -> None:
        env = self._env()
        env["MOCK_AVAILABLE_KB"] = "1"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INSUFFICIENT_DESTINATION_CAPACITY", result.stderr)
        self.assertNotIn("pg_dump --username", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_windows_destination_acl_cannot_be_proven_and_fails_closed(self) -> None:
        env = self._env()
        env["MOCK_UNAME"] = "MINGW64_NT-10.0"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DESTINATION_ACL_UNVERIFIABLE", result.stderr)
        self.assertEqual(self._docker_calls(), "")
        self.assertFalse(any(self.destination.iterdir()))

    def test_destination_inside_repository_is_rejected(self) -> None:
        result = self._run(destination=ROOT)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DESTINATION_INSIDE_REPOSITORY", result.stderr)
        self.assertEqual(self._docker_calls(), "")
        self.assertFalse(any(self.destination.iterdir()))

    def test_invalid_archive_is_not_published(self) -> None:
        result = self._run(scenario="invalid_archive")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ARCHIVE_VALIDATION_FAILED", result.stderr)
        self.assertFalse(list(self.destination.glob("sitara-backup-*")))
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_empty_archive_is_not_published(self) -> None:
        result = self._run(scenario="empty_archive")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMPTY_ARCHIVE", result.stderr)
        self.assertFalse(list(self.destination.glob("sitara-backup-*")))
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_encryption_failure_cleans_partial_output_and_redacts_diagnostics(self) -> None:
        env = self._env()
        env["MOCK_AGE_FAIL"] = "1"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENCRYPTION_FAILED", result.stderr)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", result.stdout + result.stderr)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_staging_cleanup_failure_is_reported(self) -> None:
        env = self._env()
        env["MOCK_AGE_FAIL"] = "1"
        env["MOCK_STAGING_CLEANUP_FAIL"] = "1"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ENCRYPTION_FAILED", result.stderr)
        self.assertIn("STAGING_CLEANUP_FAILED", result.stderr)
        staging_dirs = list(self.destination.glob(".sitara-backup-*"))
        self.assertEqual(len(staging_dirs), 1)
        self.assertTrue((staging_dirs[0] / "database.dump").is_file())
        self.assertFalse(list(self.destination.glob("sitara-backup-*")))

    def test_manifest_encryption_failure_does_not_publish_plaintext_metadata(self) -> None:
        env = self._env()
        env["MOCK_AGE_FAIL_AT"] = "2"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MANIFEST_ENCRYPTION_FAILED", result.stderr)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_connection_errors_do_not_leak_command_diagnostics(self) -> None:
        result = self._run(scenario="connection_failure")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_DATABASE_UNAVAILABLE", result.stderr)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", result.stdout + result.stderr)
        self.assertFalse(any(self.destination.iterdir()))

    def test_atomic_publish_collision_does_not_publish_or_overwrite(self) -> None:
        env = self._env()
        env["MOCK_PUBLISH_FAIL"] = "1"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ATOMIC_PUBLISH_COLLISION", result.stderr)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_database_connection_must_match_the_requested_database(self) -> None:
        result = self._run(scenario="database_mismatch")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_DATABASE_MISMATCH", result.stderr)
        self.assertNotIn("pg_dump --username", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_backup_role_with_privileged_attributes_is_rejected(self) -> None:
        result = self._run(scenario="overprivileged_backup_role")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BACKUP_ROLE_OVERPRIVILEGED", result.stderr)
        self.assertNotIn("pg_dump --username", self._docker_calls())
        self.assertFalse(any(self.destination.iterdir()))

    def test_age_unavailable_fails_closed_without_creating_a_backup(self) -> None:
        env = self._env()
        env["PATH"] = os.pathsep.join(
            (str(self.bin_dir), os.path.dirname(os.environ.get("PATH", "")))
        )
        (self.bin_dir / "age").unlink()

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AGE_TOOL_UNAVAILABLE", result.stderr)
        self.assertFalse(list(self.destination.glob("sitara-backup-*")))


if __name__ == "__main__":
    unittest.main()
