#!/usr/bin/env bash
# Requires a pre-provisioned, one-use disposable PostgreSQL 16 container.
set -Eeuo pipefail
umask 077

STATUS="FAILED"
ERROR_CODE="VALIDATION_FAILED"
ERROR_MESSAGE="Restore did not complete"
CURRENT_STAGE="argument validation"
FINAL_EXIT_CODE=1
REPORT_PATH=""
REPORT_TEMP=""
TEMP_DIR=""
TARGET_DB=""
CONTAINER_ID=""
RUN_ID=""
DB_USER=""
SERVER_VERSION="UNKNOWN"
ALEMBIC_REVISION="NOT_AVAILABLE"
TABLE_COUNT="UNKNOWN"
CHECKSUM_STATUS="NOT_PROVIDED"
INPUT_MODE="plaintext"
BACKUP=""
TARGET_DB=""
REPORT_PATH=""
BUNDLE_DIRECTORY=""
AGE_IDENTITY=""

fail() {
  ERROR_CODE="$1"
  ERROR_MESSAGE="$2"
  FINAL_EXIT_CODE="${3:-1}"
  printf 'ERROR: %s\n' "$ERROR_MESSAGE" >&2
  exit "$FINAL_EXIT_CODE"
}

on_error() {
  local exit_code="$1"
  local line="$2"
  STATUS="FAILED"
  ERROR_CODE="COMMAND_FAILED"
  ERROR_MESSAGE="A command failed during ${CURRENT_STAGE} (line ${line})"
  FINAL_EXIT_CODE="$exit_code"
  exit "$exit_code"
}

on_signal() {
  STATUS="INTERRUPTED"
  ERROR_CODE="INTERRUPTED"
  ERROR_MESSAGE="Restore interrupted during ${CURRENT_STAGE}"
  FINAL_EXIT_CODE=130
  exit 130
}

write_report() {
  local report_status="$STATUS"
  if [[ -z "$REPORT_PATH" || -z "$REPORT_TEMP" || ! -f "$REPORT_TEMP" ]]; then
    return
  fi

  {
    printf 'format_version=1\n'
    printf 'status=%s\n' "$report_status"
    printf 'target_database=%s\n' "${TARGET_DB:-UNKNOWN}"
    printf 'target_container_id=%s\n' "${CONTAINER_ID:-UNKNOWN}"
    printf 'disposable_run_id=%s\n' "${RUN_ID:-UNKNOWN}"
    printf 'postgres_server_version=%s\n' "$SERVER_VERSION"
    printf 'alembic_revision=%s\n' "$ALEMBIC_REVISION"
    printf 'table_count=%s\n' "$TABLE_COUNT"
    printf 'archive_checksum_status=%s\n' "$CHECKSUM_STATUS"
    printf 'error_code=%s\n' "$ERROR_CODE"
    printf 'error_message=%s\n' "$ERROR_MESSAGE"
  } > "$REPORT_TEMP"

  if ln "$REPORT_TEMP" "$REPORT_PATH" 2>/dev/null; then
    rm -f -- "$REPORT_TEMP"
    REPORT_TEMP=""
  else
    printf 'ERROR: Could not publish the restore report without overwriting an existing file.\n' >&2
    FINAL_EXIT_CODE=1
  fi
}

on_exit() {
  local exit_code="$1"
  if [[ "$STATUS" == "FAILED" && "$ERROR_CODE" == "VALIDATION_FAILED" ]]; then
    FINAL_EXIT_CODE="$exit_code"
  fi
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    if ! rm -rf -- "$TEMP_DIR" || [[ -e "$TEMP_DIR" || -L "$TEMP_DIR" ]]; then
      STATUS="FAILED"
      ERROR_CODE="TEMP_CLEANUP_FAILED"
      ERROR_MESSAGE="Could not remove the private temporary directory."
      FINAL_EXIT_CODE=1
      printf 'ERROR: %s\n' "$ERROR_MESSAGE" >&2
    fi
  fi
  write_report
  if [[ -n "$REPORT_TEMP" && -f "$REPORT_TEMP" ]]; then
    if ! rm -f -- "$REPORT_TEMP"; then
      printf 'ERROR: Could not remove the private temporary report file.\n' >&2
      FINAL_EXIT_CODE=1
    fi
  fi
  exit "$FINAL_EXIT_CODE"
}

trap 'on_error "$?" "$LINENO"' ERR
trap on_signal INT TERM HUP
trap 'on_exit "$?"' EXIT

if [[ "$#" -eq 3 ]]; then
  BACKUP="$1"
  TARGET_DB="$2"
  REPORT_PATH="$3"
elif [[ "$#" -eq 5 && "$1" == "--encrypted" ]]; then
  INPUT_MODE="encrypted"
  BUNDLE_DIRECTORY="$2"
  AGE_IDENTITY="$3"
  BACKUP="${BUNDLE_DIRECTORY}/database.dump.age"
  TARGET_DB="$4"
  REPORT_PATH="$5"
else
  fail "USAGE" "Usage: $0 <backup.dump> <new_sitara_restore_database_name> <new_report_path> | $0 --encrypted <backup_bundle_directory> <age_identity_file> <new_sitara_restore_database_name> <new_report_path>" 2
fi

if ! command -v docker >/dev/null 2>&1 ||
  ! command -v mktemp >/dev/null 2>&1 ||
  ! command -v awk >/dev/null 2>&1 ||
  ! command -v chmod >/dev/null 2>&1 ||
  ! command -v cp >/dev/null 2>&1 ||
  ! command -v dirname >/dev/null 2>&1 ||
  ! command -v grep >/dev/null 2>&1 ||
  ! command -v ln >/dev/null 2>&1 ||
  ! command -v rm >/dev/null 2>&1 ||
  ! command -v sed >/dev/null 2>&1; then
  fail "MISSING_TOOL" "Required shell and Docker tools are unavailable."
fi
if [[ "$INPUT_MODE" == "encrypted" ]] &&
  (! command -v age >/dev/null 2>&1 ||
    ! command -v python >/dev/null 2>&1 ||
    ! command -v stat >/dev/null 2>&1); then
  fail "MISSING_ENCRYPTED_RESTORE_TOOL" "age and Python are required for encrypted backup restore."
fi
if [[ -e "$REPORT_PATH" || -L "$REPORT_PATH" ]]; then
  fail "REPORT_EXISTS" "Restore report path already exists; refusing to overwrite it."
fi
REPORT_DIRECTORY="$(dirname -- "$REPORT_PATH")"
if [[ ! -d "$REPORT_DIRECTORY" || ! -w "$REPORT_DIRECTORY" ]]; then
  fail "INVALID_REPORT_DIRECTORY" "Restore report directory must already exist and be writable."
fi
if [[ "$REPORT_PATH" == "$BACKUP" || "$REPORT_PATH" == "${BACKUP}.sha256" ]]; then
  fail "INVALID_REPORT_PATH" "Restore report must not overwrite the archive or its checksum."
fi
if [[ "$INPUT_MODE" == "encrypted" &&
  ( "$REPORT_PATH" == "${BUNDLE_DIRECTORY}/manifest.json.age" ||
    "$REPORT_PATH" == "${BUNDLE_DIRECTORY}/manifest.json.age.sha256" ) ]]; then
  fail "INVALID_REPORT_PATH" "Restore report must not overwrite encrypted bundle files."
fi

REPORT_TEMP="$(mktemp "${REPORT_PATH}.tmp.XXXXXX")" ||
  fail "REPORT_CREATE_FAILED" "Could not create a private temporary report."
TEMP_DIR="$(mktemp -d)" ||
  fail "TEMP_CREATE_FAILED" "Could not create a private temporary directory."

for required in \
  SITARA_RESTORE_ENVIRONMENT \
  SITARA_RESTORE_CONTAINER_ID \
  SITARA_RESTORE_TARGET_HOST \
  SITARA_RESTORE_TARGET_PORT \
  SITARA_RESTORE_RUN_ID \
  SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER \
  SITARA_RESTORE_DB_USER; do
  if [[ -z "${!required:-}" ]]; then
    fail "MISSING_CONFIGURATION" "Required restore target configuration is missing: ${required}"
  fi
done

if [[ "$SITARA_RESTORE_ENVIRONMENT" != "disposable" ]]; then
  fail "INVALID_ENVIRONMENT" "Restore target environment must be explicitly identified as disposable."
fi
if [[ "$TARGET_DB" == "sitara_dev" || "$TARGET_DB" == "sitara_test" ]]; then
  fail "PROTECTED_DATABASE" "Refusing to restore to a protected SITARA database."
fi
if [[ -n "${SITARA_RESTORE_PROTECTED_DATABASES:-}" ]]; then
  IFS=',' read -r -a protected_databases <<< "$SITARA_RESTORE_PROTECTED_DATABASES"
  for protected_database in "${protected_databases[@]}"; do
    if [[ ! "$protected_database" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]]; then
      fail "INVALID_PROTECTED_DATABASE_CONFIGURATION" "Protected database configuration is invalid."
    fi
    if [[ "$TARGET_DB" == "$protected_database" ]]; then
      fail "PROTECTED_DATABASE" "Refusing to restore to a protected SITARA database."
    fi
  done
fi
if [[ ! "$SITARA_RESTORE_CONTAINER_ID" =~ ^[a-fA-F0-9]{64}$ ]]; then
  fail "INVALID_CONTAINER_ID" "A full Docker container ID is required."
fi
CONTAINER_ID="$SITARA_RESTORE_CONTAINER_ID"
if [[ ! "$SITARA_RESTORE_RUN_ID" =~ ^[a-z0-9_-]{8,48}$ ]]; then
  fail "INVALID_RUN_ID" "A valid disposable restore run ID is required."
fi
RUN_ID="$SITARA_RESTORE_RUN_ID"
EXPECTED_TARGET_DB="sitara_restore_${RUN_ID//-/_}"
if [[ "$TARGET_DB" != "$EXPECTED_TARGET_DB" ]]; then
  fail "INVALID_DATABASE_NAME" "Target database name must be derived from the disposable restore run ID."
fi
if [[ ! "$SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER" =~ ^[0-9]{10,20}$ ]]; then
  fail "INVALID_CLUSTER_IDENTITY" "A verified PostgreSQL system identifier is required."
fi
if [[ ! "$SITARA_RESTORE_DB_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]]; then
  fail "INVALID_DATABASE_USER" "A valid disposable database user is required."
fi
DB_USER="$SITARA_RESTORE_DB_USER"
if [[ "$DB_USER" == "sitara_app" ]]; then
  fail "APPLICATION_ROLE_FORBIDDEN" "The application database role cannot be used for restore."
fi
if [[ "${SITARA_RESTORE_TARGET_HOST,,}" != "container:${CONTAINER_ID,,}" ]]; then
  fail "INVALID_TARGET_HOST" "Target host must identify the verified disposable container."
fi
if [[ "$SITARA_RESTORE_TARGET_PORT" != "5432" ]]; then
  fail "INVALID_TARGET_PORT" "Disposable PostgreSQL must listen on its internal port 5432."
fi
TARGET_PORT="$SITARA_RESTORE_TARGET_PORT"

ARCHIVE_FILE="${TEMP_DIR}/restore-input.dump"
if [[ "$INPUT_MODE" == "encrypted" ]]; then
  if [[ ! -d "$BUNDLE_DIRECTORY" || -L "$BUNDLE_DIRECTORY" ]]; then
    fail "INVALID_BUNDLE_DIRECTORY" "Encrypted backup bundle must be a directory, not a symbolic link."
  fi
  MANIFEST_CIPHER="${BUNDLE_DIRECTORY}/manifest.json.age"
  MANIFEST_CHECKSUM="${MANIFEST_CIPHER}.sha256"
  ARCHIVE_CHECKSUM="${BACKUP}.sha256"
  for bundle_file in "$BACKUP" "$ARCHIVE_CHECKSUM" "$MANIFEST_CIPHER" "$MANIFEST_CHECKSUM"; do
    if [[ ! -f "$bundle_file" || -L "$bundle_file" || ! -r "$bundle_file" ]]; then
      fail "INVALID_ENCRYPTED_BUNDLE" "Encrypted backup bundle is missing a regular required file."
    fi
  done
  if [[ ! -s "$BACKUP" || ! -s "$MANIFEST_CIPHER" ]]; then
    fail "EMPTY_ENCRYPTED_FILE" "Encrypted archive and manifest must not be empty."
  fi
  if [[ ! -f "$AGE_IDENTITY" || -L "$AGE_IDENTITY" || ! -r "$AGE_IDENTITY" ]]; then
    fail "INVALID_AGE_IDENTITY" "age identity must be a readable regular file, not a symbolic link."
  fi

  verify_checksum() {
    local file="$1"
    local checksum_file="$2"
    local expected actual
    read -r expected _ < "$checksum_file" || true
    expected="${expected%$'\r'}"
    if [[ ! "$expected" =~ ^[a-fA-F0-9]{64}$ ]]; then
      fail "INVALID_CHECKSUM" "Checksum sidecar does not contain a valid SHA-256 digest."
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      actual="$(sha256sum < "$file" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
      actual="$(shasum -a 256 < "$file" | awk '{print $1}')"
    else
      fail "MISSING_CHECKSUM_TOOL" "A SHA-256 utility is required to verify the encrypted bundle."
    fi
    if [[ "${actual,,}" != "${expected,,}" ]]; then
      fail "CHECKSUM_MISMATCH" "Encrypted backup SHA-256 does not match its sidecar."
    fi
    VERIFIED_SHA256="${actual,,}"
  }

  verify_checksum "$MANIFEST_CIPHER" "$MANIFEST_CHECKSUM"
  verify_checksum "$BACKUP" "$ARCHIVE_CHECKSUM"
  ENCRYPTED_ARCHIVE_SHA256="$VERIFIED_SHA256"
  if ! age --decrypt --identity "$AGE_IDENTITY" \
    --output "${TEMP_DIR}/manifest.json" "$MANIFEST_CIPHER" 2>/dev/null; then
    fail "DECRYPTION_FAILED" "Could not decrypt encrypted backup manifest with the supplied identity."
  fi
  if [[ ! -f "${TEMP_DIR}/manifest.json" || -L "${TEMP_DIR}/manifest.json" ||
    ! -s "${TEMP_DIR}/manifest.json" ]] || ! chmod 400 "${TEMP_DIR}/manifest.json"; then
    fail "MANIFEST_DECRYPTION_FAILED" "Decrypted backup manifest is not a valid staged file."
  fi
  if ! MANIFEST_FIELDS="$(python -c '
import json
import re
import sys

try:
    manifest = json.load(sys.stdin.buffer)
    if (
        manifest["status"] != "COMPLETE"
        or manifest["encryption"] != "age"
        or manifest["archive_format"] != "custom"
        or manifest["encrypted_file"] != "database.dump.age"
        or not isinstance(manifest["plaintext_archive_size_bytes"], int)
        or isinstance(manifest["plaintext_archive_size_bytes"], bool)
        or manifest["plaintext_archive_size_bytes"] <= 0
        or not isinstance(manifest["encrypted_file_size_bytes"], int)
        or isinstance(manifest["encrypted_file_size_bytes"], bool)
        or manifest["encrypted_file_size_bytes"] <= 0
        or not re.fullmatch(r"[a-fA-F0-9]{64}", manifest["plaintext_archive_sha256"])
        or not re.fullmatch(r"[a-fA-F0-9]{64}", manifest["encrypted_file_sha256"])
    ):
        raise ValueError("invalid manifest fields")
    print(
        "\t".join(
            (
                str(manifest["plaintext_archive_size_bytes"]),
                manifest["plaintext_archive_sha256"].lower(),
                str(manifest["encrypted_file_size_bytes"]),
                manifest["encrypted_file_sha256"].lower(),
            )
        )
    )
except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
    sys.exit(1)
' < "${TEMP_DIR}/manifest.json" 2>/dev/null)"; then
    fail "INVALID_MANIFEST" "Decrypted backup manifest is invalid or incomplete."
  fi
  IFS=$'\t' read -r EXPECTED_PLAINTEXT_SIZE EXPECTED_PLAINTEXT_SHA256 \
    EXPECTED_CIPHERTEXT_SIZE EXPECTED_CIPHERTEXT_SHA256 <<< "$MANIFEST_FIELDS"
  ACTUAL_CIPHERTEXT_SIZE="$(stat -c '%s' -- "$BACKUP" 2>/dev/null)" ||
    fail "CIPHERTEXT_SIZE_UNAVAILABLE" "Could not verify encrypted archive size."
  if [[ "$ACTUAL_CIPHERTEXT_SIZE" != "$EXPECTED_CIPHERTEXT_SIZE" ||
    "$ENCRYPTED_ARCHIVE_SHA256" != "$EXPECTED_CIPHERTEXT_SHA256" ]]; then
    fail "CIPHERTEXT_MANIFEST_MISMATCH" "Encrypted archive does not match the decrypted manifest."
  fi
  if ! age --decrypt --identity "$AGE_IDENTITY" \
    --output "$ARCHIVE_FILE" "$BACKUP" 2>/dev/null; then
    fail "DECRYPTION_FAILED" "Could not decrypt encrypted PostgreSQL archive with the supplied identity."
  fi
  if [[ ! -f "$ARCHIVE_FILE" || -L "$ARCHIVE_FILE" || ! -s "$ARCHIVE_FILE" ]] ||
    ! chmod 400 "$ARCHIVE_FILE"; then
    fail "ARCHIVE_STAGE_FAILED" "Decrypted PostgreSQL archive is not a valid staged file."
  fi
  ACTUAL_PLAINTEXT_SIZE="$(stat -c '%s' -- "$ARCHIVE_FILE" 2>/dev/null)" ||
    fail "PLAINTEXT_SIZE_UNAVAILABLE" "Could not verify decrypted archive size."
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_PLAINTEXT_SHA256="$(sha256sum -- "$ARCHIVE_FILE" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL_PLAINTEXT_SHA256="$(shasum -a 256 -- "$ARCHIVE_FILE" | awk '{print $1}')"
  else
    fail "MISSING_CHECKSUM_TOOL" "A SHA-256 utility is required to verify decrypted archive."
  fi
  if [[ "$ACTUAL_PLAINTEXT_SIZE" != "$EXPECTED_PLAINTEXT_SIZE" ||
    "${ACTUAL_PLAINTEXT_SHA256,,}" != "$EXPECTED_PLAINTEXT_SHA256" ]]; then
    fail "PLAINTEXT_CHECKSUM_MISMATCH" "Decrypted archive size or SHA-256 does not match the manifest."
  fi
  CHECKSUM_STATUS="VERIFIED"
else
  if [[ ! -f "$BACKUP" || -L "$BACKUP" || ! -r "$BACKUP" ]]; then
    fail "INVALID_ARCHIVE_FILE" "Backup must be a readable regular file, not a symbolic link."
  fi
  if [[ ! -s "$BACKUP" ]]; then
    fail "EMPTY_ARCHIVE" "Backup archive is empty."
  fi
  if ! cp -- "$BACKUP" "$ARCHIVE_FILE"; then
    fail "ARCHIVE_STAGE_FAILED" "Could not stage the backup in a private temporary directory."
  fi
  if [[ ! -f "$ARCHIVE_FILE" || -L "$ARCHIVE_FILE" || ! -s "$ARCHIVE_FILE" ]]; then
    fail "ARCHIVE_STAGE_FAILED" "Staged backup is not a non-empty regular file."
  fi
  if ! chmod 400 "$ARCHIVE_FILE"; then
    fail "ARCHIVE_STAGE_FAILED" "Could not make the staged backup read-only."
  fi

  CHECKSUM_FILE="${BACKUP}.sha256"
  if [[ -e "$CHECKSUM_FILE" || -L "$CHECKSUM_FILE" ]]; then
    if [[ ! -f "$CHECKSUM_FILE" || -L "$CHECKSUM_FILE" || ! -r "$CHECKSUM_FILE" ]]; then
      fail "INVALID_CHECKSUM_FILE" "Checksum sidecar must be a readable regular file."
    fi
    read -r EXPECTED_SHA256 _ < "$CHECKSUM_FILE" || true
    EXPECTED_SHA256="${EXPECTED_SHA256%$'\r'}"
    if [[ ! "${EXPECTED_SHA256:-}" =~ ^[a-fA-F0-9]{64}$ ]]; then
      fail "INVALID_CHECKSUM" "Checksum sidecar does not contain a valid SHA-256 digest."
    fi
    if command -v sha256sum >/dev/null 2>&1; then
      ACTUAL_SHA256="$(sha256sum -- "$ARCHIVE_FILE" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
      ACTUAL_SHA256="$(shasum -a 256 -- "$ARCHIVE_FILE" | awk '{print $1}')"
    else
      fail "MISSING_CHECKSUM_TOOL" "A SHA-256 utility is required when a checksum is supplied."
    fi
    if [[ "${ACTUAL_SHA256,,}" != "${EXPECTED_SHA256,,}" ]]; then
      fail "CHECKSUM_MISMATCH" "Backup SHA-256 does not match its sidecar."
    fi
    CHECKSUM_STATUS="VERIFIED"
  else
    CHECKSUM_STATUS="NOT_PROVIDED"
    printf 'WARNING: No SHA-256 sidecar was provided; archive integrity is limited to format validation.\n' >&2
  fi
fi

CURRENT_STAGE="disposable container identity validation"
INSPECT_TEMPLATE='{{.Id}}|{{.State.Running}}|{{.Config.Image}}|{{index .Config.Labels "sitara.restore.disposable"}}|{{index .Config.Labels "sitara.restore.run_id"}}|{{index .Config.Labels "com.docker.compose.project"}}|{{if index .HostConfig.Tmpfs "/var/lib/postgresql/data"}}true{{else}}false{{end}}|{{len .HostConfig.Tmpfs}}|{{range .Mounts}}{{if ne .Type "tmpfs"}}persistent,{{end}}{{end}}|{{range $port, $bindings := .NetworkSettings.Ports}}{{if $bindings}}published,{{end}}{{end}}'
if ! INSPECT_RESULT="$(docker inspect --format "$INSPECT_TEMPLATE" "$CONTAINER_ID" 2>/dev/null)"; then
  fail "CONTAINER_NOT_VERIFIED" "Could not inspect the requested disposable PostgreSQL container."
fi
IFS='|' read -r INSPECTED_ID CONTAINER_RUNNING IMAGE_NAME DISPOSABLE_LABEL CONTAINER_RUN_ID COMPOSE_PROJECT DATA_TMPFS TMPFS_COUNT PERSISTENT_MOUNTS PUBLISHED_PORTS <<< "$INSPECT_RESULT"
IMAGE_PATTERN='^postgres:16([.-].*)?$'
if [[ "${INSPECTED_ID,,}" != "${CONTAINER_ID,,}" ]] ||
  [[ "$CONTAINER_RUNNING" != "true" ]] ||
  [[ "$DISPOSABLE_LABEL" != "true" ]] ||
  [[ "$CONTAINER_RUN_ID" != "$RUN_ID" ]] ||
  [[ "$COMPOSE_PROJECT" != "<no value>" && -n "$COMPOSE_PROJECT" ]] ||
  [[ ! "$IMAGE_NAME" =~ $IMAGE_PATTERN ]] ||
  [[ "$DATA_TMPFS" != "true" ]] ||
  [[ "$TMPFS_COUNT" != "1" ]] ||
  [[ -n "$PERSISTENT_MOUNTS" ]] ||
  [[ -n "$PUBLISHED_PORTS" ]]; then
  fail "UNSAFE_CONTAINER" "Container is not a verified isolated PostgreSQL 16 disposable target."
fi

NETWORK_TEMPLATE='{{range $name, $network := .NetworkSettings.Networks}}{{$network.NetworkID}}{{"\n"}}{{end}}'
if ! NETWORK_IDS="$(docker inspect --format "$NETWORK_TEMPLATE" "$CONTAINER_ID" 2>/dev/null)"; then
  fail "NETWORK_NOT_VERIFIED" "Could not verify the disposable container network."
fi
NETWORK_IDS="$(printf '%s\n' "$NETWORK_IDS" | sed '/^[[:space:]]*$/d')"
if [[ ! "$NETWORK_IDS" =~ ^[a-fA-F0-9]{64}$ ]]; then
  fail "NETWORK_NOT_ISOLATED" "Disposable container must use exactly one verifiable Docker network."
fi
NETWORK_TEMPLATE='{{len .Containers}}|{{range $id, $container := .Containers}}{{$id}}|{{end}}'
if ! NETWORK_RESULT="$(docker network inspect --format "$NETWORK_TEMPLATE" "$NETWORK_IDS" 2>/dev/null)"; then
  fail "NETWORK_NOT_VERIFIED" "Could not inspect the disposable Docker network."
fi
IFS='|' read -r NETWORK_CONTAINER_COUNT NETWORK_CONTAINER_ID _ <<< "$NETWORK_RESULT"
if [[ "$NETWORK_CONTAINER_COUNT" != "1" || "${NETWORK_CONTAINER_ID,,}" != "${CONTAINER_ID,,}" ]]; then
  fail "NETWORK_NOT_ISOLATED" "Disposable restore network must contain only the target container."
fi

psql_scalar() {
  local database="$1"
  local query="$2"
  docker exec "$CONTAINER_ID" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --tuples-only --no-align --username "$DB_USER" --dbname "$database" \
    --command "$query" 2>/dev/null | sed '/^[[:space:]]*$/d'
}

CURRENT_STAGE="PostgreSQL cluster identity validation"
SYSTEM_IDENTIFIER="$(psql_scalar postgres 'SELECT system_identifier FROM pg_control_system()')" ||
  fail "CLUSTER_IDENTITY_UNAVAILABLE" "Could not read PostgreSQL cluster identity from the disposable target."
if [[ "$SYSTEM_IDENTIFIER" != "$SITARA_RESTORE_EXPECTED_SYSTEM_IDENTIFIER" ]]; then
  fail "CLUSTER_IDENTITY_MISMATCH" "PostgreSQL system identifier does not match the approved disposable target."
fi

SERVER_VERSION_NUM="$(psql_scalar postgres 'SHOW server_version_num')" ||
  fail "SERVER_VERSION_UNAVAILABLE" "Could not read PostgreSQL server version."
if [[ ! "$SERVER_VERSION_NUM" =~ ^[0-9]{5,6}$ ]] || (( SERVER_VERSION_NUM / 10000 != 16 )); then
  fail "INCOMPATIBLE_SERVER_VERSION" "Disposable target must run PostgreSQL 16."
fi
SERVER_VERSION="$(psql_scalar postgres 'SHOW server_version')" ||
  fail "SERVER_VERSION_UNAVAILABLE" "Could not read PostgreSQL server version."
SERVER_PORT="$(psql_scalar postgres 'SHOW port')" ||
  fail "SERVER_PORT_UNAVAILABLE" "Could not read PostgreSQL server port."
if [[ "$SERVER_PORT" != "$TARGET_PORT" ]]; then
  fail "SERVER_PORT_MISMATCH" "PostgreSQL server port does not match the disposable target configuration."
fi
DATA_DIRECTORY="$(psql_scalar postgres 'SHOW data_directory')" ||
  fail "DATA_DIRECTORY_UNAVAILABLE" "Could not verify the disposable PostgreSQL data directory."
if [[ "$DATA_DIRECTORY" != "/var/lib/postgresql/data" ]]; then
  fail "DATA_DIRECTORY_MISMATCH" "PostgreSQL data directory does not match the required tmpfs mount."
fi

CURRENT_STAGE="archive checksum and format validation"
if ! docker exec -i "$CONTAINER_ID" pg_restore --list < "$ARCHIVE_FILE" > "${TEMP_DIR}/archive.list" 2>/dev/null; then
  fail "INVALID_ARCHIVE" "PostgreSQL rejected the backup archive format."
fi
DUMPED_FROM_VERSION="$(grep -m 1 '^;[[:space:]]*Dumped from database version:' "${TEMP_DIR}/archive.list" | sed -E 's/^;[[:space:]]*Dumped from database version: ([0-9]+).*/\1/' || true)"
if [[ "$DUMPED_FROM_VERSION" != "16" ]]; then
  fail "INCOMPATIBLE_ARCHIVE_VERSION" "Archive source version is missing or incompatible with PostgreSQL 16."
fi
if ! RESTORE_TOOL_VERSION="$(docker exec "$CONTAINER_ID" pg_restore --version 2>/dev/null)"; then
  fail "RESTORE_TOOL_UNAVAILABLE" "Could not verify pg_restore version in the disposable target."
fi
RESTORE_TOOL_MAJOR="$(printf '%s\n' "$RESTORE_TOOL_VERSION" | sed -nE 's/^pg_restore \(PostgreSQL\) ([0-9]+)\..*/\1/p')"
if [[ "$RESTORE_TOOL_MAJOR" != "16" ]]; then
  fail "INCOMPATIBLE_RESTORE_TOOL" "Disposable pg_restore client must be PostgreSQL 16."
fi

CURRENT_STAGE="target database preflight"
DATABASE_EXISTS="$(psql_scalar postgres "SELECT COUNT(*) FROM pg_catalog.pg_database WHERE datname = '${TARGET_DB}'")" ||
  fail "DATABASE_PREFLIGHT_FAILED" "Could not verify whether the target database already exists."
if [[ ! "$DATABASE_EXISTS" =~ ^[0-9]+$ ]]; then
  fail "DATABASE_PREFLIGHT_FAILED" "Target database existence check returned an invalid result."
fi
if (( DATABASE_EXISTS != 0 )); then
  fail "DATABASE_ALREADY_EXISTS" "Target database already exists; existing databases are never replaced."
fi
USER_DATABASE_COUNT="$(psql_scalar postgres "SELECT COUNT(*) FROM pg_catalog.pg_database WHERE datistemplate = false AND datname <> 'postgres'")" ||
  fail "DATABASE_PREFLIGHT_FAILED" "Could not verify that the disposable cluster is otherwise empty."
if [[ ! "$USER_DATABASE_COUNT" =~ ^[0-9]+$ ]] || (( USER_DATABASE_COUNT != 0 )); then
  fail "NONEMPTY_DISPOSABLE_CLUSTER" "Disposable cluster must contain no pre-existing user databases."
fi

CURRENT_STAGE="new target database creation"
if ! docker exec "$CONTAINER_ID" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
  --username "$DB_USER" --dbname postgres --command "CREATE DATABASE \"${TARGET_DB}\"" >/dev/null 2>&1; then
  fail "DATABASE_CREATE_FAILED" "Could not create the new target database; no existing database was removed."
fi

CURRENT_STAGE="archive restore"
if ! docker exec -i "$CONTAINER_ID" pg_restore --exit-on-error --no-owner --no-acl \
  --username "$DB_USER" --dbname "$TARGET_DB" < "$ARCHIVE_FILE" >/dev/null 2>&1; then
  fail "RESTORE_FAILED" "PostgreSQL restore failed; the new disposable database may be partial and was not removed."
fi

CURRENT_STAGE="post-restore validation"
if [[ "$(psql_scalar "$TARGET_DB" 'SELECT 1')" != "1" ]]; then
  fail "POST_RESTORE_CONNECTION_FAILED" "Could not verify a connection to the restored database."
fi
SERVER_VERSION="$(psql_scalar "$TARGET_DB" 'SHOW server_version')" ||
  fail "POST_RESTORE_VERSION_FAILED" "Could not verify the restored database server version."
HAS_ALEMBIC_VERSION="$(psql_scalar "$TARGET_DB" "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'alembic_version'")" ||
  fail "POST_RESTORE_REVISION_CHECK_FAILED" "Could not inspect Alembic revision availability."
if [[ "$HAS_ALEMBIC_VERSION" == "1" ]]; then
  ALEMBIC_REVISION="$(psql_scalar "$TARGET_DB" 'SELECT version_num FROM alembic_version')" ||
    fail "POST_RESTORE_REVISION_CHECK_FAILED" "Could not read the Alembic revision."
  if [[ ! "$ALEMBIC_REVISION" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
    ALEMBIC_REVISION="UNAVAILABLE"
  fi
fi
TABLE_COUNT="$(psql_scalar "$TARGET_DB" "SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')")" ||
  fail "POST_RESTORE_TABLE_CHECK_FAILED" "Could not count restored application tables."
if [[ ! "$TABLE_COUNT" =~ ^[0-9]+$ ]]; then
  fail "POST_RESTORE_TABLE_CHECK_FAILED" "Restored table count is invalid."
fi

STATUS="PASS"
ERROR_CODE="NONE"
ERROR_MESSAGE="Restore and non-sensitive database checks completed"
FINAL_EXIT_CODE=0
printf 'Restore validation passed for a new disposable database; a report was generated.\n'
