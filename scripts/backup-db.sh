#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/backup-db.sh \
    --container-id FULL_CONTAINER_ID \
    --expected-system-identifier SYSTEM_IDENTIFIER \
    --database DATABASE --database-user ROLE --allow-database DATABASE \
    --environment ENVIRONMENT --destination EXISTING_PRIVATE_DIRECTORY \
    --age-recipient AGE_RECIPIENT

Repeat --allow-database to provide the explicit database allowlist.
Only PostgreSQL 16 sources are supported by this restore workflow.
EOF
}

fail() {
  printf 'BACKUP_FAILED code=%s\n' "$1" >&2
  exit 1
}

CONTAINER_ID=""
EXPECTED_SYSTEM_IDENTIFIER=""
DATABASE=""
DATABASE_USER=""
ENVIRONMENT=""
DESTINATION=""
AGE_RECIPIENT=""
declare -a ALLOWED_DATABASES=()

while (($#)); do
  case "$1" in
    --container-id)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      CONTAINER_ID="$2"
      shift 2
      ;;
    --expected-system-identifier)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      EXPECTED_SYSTEM_IDENTIFIER="$2"
      shift 2
      ;;
    --database)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      DATABASE="$2"
      shift 2
      ;;
    --database-user)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      DATABASE_USER="$2"
      shift 2
      ;;
    --allow-database)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      ALLOWED_DATABASES+=("$2")
      shift 2
      ;;
    --environment)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      ENVIRONMENT="$2"
      shift 2
      ;;
    --destination)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      DESTINATION="$2"
      shift 2
      ;;
    --age-recipient)
      (($# >= 2)) || { usage; fail "MISSING_ARGUMENT"; }
      AGE_RECIPIENT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      fail "UNKNOWN_ARGUMENT"
      ;;
  esac
done

if [[ -z "$CONTAINER_ID" || -z "$EXPECTED_SYSTEM_IDENTIFIER" || -z "$DATABASE" \
  || -z "$DATABASE_USER" || -z "$ENVIRONMENT" || -z "$DESTINATION" \
  || -z "$AGE_RECIPIENT" || ${#ALLOWED_DATABASES[@]} -eq 0 ]]; then
  usage
  fail "REQUIRED_ARGUMENT_MISSING"
fi

[[ "$CONTAINER_ID" =~ ^[a-fA-F0-9]{64}$ ]] || fail "INVALID_CONTAINER_ID"
[[ "$EXPECTED_SYSTEM_IDENTIFIER" =~ ^[0-9]{10,20}$ ]] || fail "INVALID_SYSTEM_IDENTIFIER"
[[ "$DATABASE" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || fail "INVALID_DATABASE_NAME"
[[ "$DATABASE_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || fail "INVALID_DATABASE_USER"
[[ "$ENVIRONMENT" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$ ]] || fail "INVALID_ENVIRONMENT"
[[ "$AGE_RECIPIENT" =~ ^age1[0-9a-z]{38,}$ ]] || fail "INVALID_AGE_RECIPIENT"

DATABASE_ALLOWED=false
for allowed_database in "${ALLOWED_DATABASES[@]}"; do
  [[ "$allowed_database" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] \
    || fail "INVALID_ALLOWLIST_DATABASE"
  if [[ "$DATABASE" == "$allowed_database" ]]; then
    DATABASE_ALLOWED=true
  fi
done
[[ "$DATABASE_ALLOWED" == true ]] || fail "DATABASE_NOT_ALLOWLISTED"

command -v age >/dev/null 2>&1 || fail "AGE_TOOL_UNAVAILABLE"
for command_name in docker df awk date mktemp mv rm sha256sum stat uname tr sed; do
  command -v "$command_name" >/dev/null 2>&1 || fail "REQUIRED_TOOL_UNAVAILABLE"
done

AGE_VERSION="$(age --version 2>/dev/null)" || fail "AGE_TOOL_UNAVAILABLE"
[[ "$AGE_VERSION" =~ ^[a-zA-Z0-9._+()-]+$ ]] || fail "AGE_VERSION_UNVERIFIABLE"

[[ "$DESTINATION" == /* ]] || fail "DESTINATION_NOT_ABSOLUTE"
[[ -d "$DESTINATION" && ! -L "$DESTINATION" ]] || fail "DESTINATION_NOT_DIRECTORY"
[[ -w "$DESTINATION" && -x "$DESTINATION" ]] || fail "DESTINATION_NOT_WRITABLE"
DESTINATION_REAL="$(cd -- "$DESTINATION" && pwd -P)" || fail "DESTINATION_UNVERIFIABLE"
[[ "$DESTINATION_REAL" == "$DESTINATION" ]] || fail "DESTINATION_SYMLINK_OR_NONCANONICAL"
REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" \
  || fail "REPOSITORY_ROOT_UNVERIFIABLE"
case "$DESTINATION_REAL/" in
  "$REPOSITORY_ROOT/"*) fail "DESTINATION_INSIDE_REPOSITORY" ;;
esac

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    fail "DESTINATION_ACL_UNVERIFIABLE"
    ;;
  *)
    DESTINATION_MODE="$(stat -c '%a' -- "$DESTINATION_REAL" 2>/dev/null)" \
      || fail "DESTINATION_PERMISSIONS_UNVERIFIABLE"
    [[ "$DESTINATION_MODE" =~ ^[0-7]{3,4}$ ]] || fail "DESTINATION_PERMISSIONS_UNVERIFIABLE"
    if (( (8#$DESTINATION_MODE & 077) != 0 )); then
      fail "DESTINATION_PERMISSIONS_TOO_BROAD"
    fi
    ;;
esac

AVAILABLE_KB="$(df -Pk -- "$DESTINATION_REAL" 2>/dev/null | awk 'NR == 2 { print $4 }')" \
  || fail "DESTINATION_CAPACITY_UNAVAILABLE"
[[ "$AVAILABLE_KB" =~ ^[0-9]+$ ]] || fail "DESTINATION_CAPACITY_UNAVAILABLE"

CONTAINER_METADATA="$(docker inspect --type container \
  --format '{{.Id}}|{{.State.Running}}' "$CONTAINER_ID" 2>/dev/null)" \
  || fail "SOURCE_CONTAINER_UNAVAILABLE"
IFS='|' read -r ACTUAL_CONTAINER_ID CONTAINER_RUNNING <<< "$CONTAINER_METADATA"
[[ "$ACTUAL_CONTAINER_ID" == "$CONTAINER_ID" ]] || fail "SOURCE_CONTAINER_ID_MISMATCH"
[[ "$CONTAINER_RUNNING" == true ]] || fail "SOURCE_CONTAINER_NOT_RUNNING"

psql_scalar() {
  local query="$1"
  MSYS_NO_PATHCONV=1 docker exec "$CONTAINER_ID" psql --no-psqlrc --no-password \
    --set=ON_ERROR_STOP=1 --tuples-only --no-align \
    --host=/var/run/postgresql --port=5432 \
    --username "$DATABASE_USER" --dbname "$DATABASE" --command "$query" 2>/dev/null \
    | tr -d '\r' \
    | sed -E 's/^[[:space:]]+|[[:space:]]+$//g' \
    | sed '/^$/d'
}

ACTUAL_DATABASE="$(psql_scalar 'SELECT current_database()')" || fail "SOURCE_DATABASE_UNAVAILABLE"
[[ "$ACTUAL_DATABASE" == "$DATABASE" ]] || fail "SOURCE_DATABASE_MISMATCH"
BACKUP_ROLE_PRIVILEGES="$(psql_scalar \
  'SELECT CASE WHEN rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls THEN 1 ELSE 0 END FROM pg_roles WHERE rolname = current_user')" \
  || fail "BACKUP_ROLE_PRIVILEGES_UNVERIFIABLE"
[[ "$BACKUP_ROLE_PRIVILEGES" == 0 ]] || fail "BACKUP_ROLE_OVERPRIVILEGED"

SOURCE_SYSTEM_IDENTIFIER="$(psql_scalar 'SELECT system_identifier FROM pg_control_system()')" \
  || fail "SOURCE_SYSTEM_IDENTIFIER_UNAVAILABLE"
[[ "$SOURCE_SYSTEM_IDENTIFIER" == "$EXPECTED_SYSTEM_IDENTIFIER" ]] \
  || fail "SOURCE_SYSTEM_IDENTIFIER_MISMATCH"

SERVER_VERSION_NUM="$(psql_scalar 'SHOW server_version_num')" \
  || fail "SOURCE_SERVER_VERSION_UNAVAILABLE"
[[ "$SERVER_VERSION_NUM" =~ ^[0-9]{5,6}$ ]] || fail "SOURCE_SERVER_VERSION_UNVERIFIABLE"
SERVER_MAJOR=$((SERVER_VERSION_NUM / 10000))
[[ "$SERVER_MAJOR" == 16 ]] || fail "UNSUPPORTED_POSTGRESQL_MAJOR"

DATABASE_SIZE_BYTES="$(psql_scalar 'SELECT pg_database_size(current_database())')" \
  || fail "SOURCE_DATABASE_SIZE_UNAVAILABLE"
[[ "$DATABASE_SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "SOURCE_DATABASE_SIZE_UNVERIFIABLE"

PG_DUMP_VERSION="$(docker exec "$CONTAINER_ID" pg_dump --version 2>/dev/null)" \
  || fail "PG_DUMP_UNAVAILABLE"
PG_RESTORE_VERSION="$(docker exec "$CONTAINER_ID" pg_restore --version 2>/dev/null)" \
  || fail "PG_RESTORE_UNAVAILABLE"
PSQL_VERSION="$(docker exec "$CONTAINER_ID" psql --version 2>/dev/null)" \
  || fail "PSQL_UNAVAILABLE"
PG_DUMP_MAJOR="$(sed -nE 's/^pg_dump \(PostgreSQL\) ([0-9]+)\..*/\1/p' <<< "$PG_DUMP_VERSION")"
PG_RESTORE_MAJOR="$(sed -nE 's/^pg_restore \(PostgreSQL\) ([0-9]+)\..*/\1/p' <<< "$PG_RESTORE_VERSION")"
PSQL_MAJOR="$(sed -nE 's/^psql \(PostgreSQL\) ([0-9]+)\..*/\1/p' <<< "$PSQL_VERSION")"
[[ "$PG_DUMP_MAJOR" == 16 && "$PG_RESTORE_MAJOR" == 16 && "$PSQL_MAJOR" == 16 ]] \
  || fail "POSTGRESQL_CLIENT_VERSION_MISMATCH"
PG_DUMP_VERSION_NUMBER="$(sed -nE 's/^pg_dump \(PostgreSQL\) ([0-9]+(\.[0-9]+)+).*/\1/p' <<< "$PG_DUMP_VERSION")"
[[ "$PG_DUMP_VERSION_NUMBER" =~ ^[0-9]+(\.[0-9]+)+$ ]] \
  || fail "PG_DUMP_VERSION_UNVERIFIABLE"

MINIMUM_FREE_KB=$((( (DATABASE_SIZE_BYTES + 1023) / 1024 ) * 3 + 16384))
(( AVAILABLE_KB >= MINIMUM_FREE_KB )) || fail "INSUFFICIENT_DESTINATION_CAPACITY"

STARTED_AT_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || fail "UTC_CLOCK_UNAVAILABLE"
BACKUP_STAMP="$(date -u '+%Y%m%dT%H%M%SZ')" || fail "UTC_CLOCK_UNAVAILABLE"
STAGING_DIR="$(mktemp -d "$DESTINATION_REAL/.sitara-backup-${BACKUP_STAMP}.XXXXXX")" \
  || fail "STAGING_DIRECTORY_CREATE_FAILED"
STAGING_BASENAME="${STAGING_DIR##*/}"
BACKUP_TOKEN="${STAGING_BASENAME##*.}"
BACKUP_ID="sitara-backup-${ENVIRONMENT}-${BACKUP_STAMP}-${BACKUP_TOKEN}"
FINAL_DIRECTORY="${DESTINATION_REAL}/${BACKUP_ID}"

cleanup() {
  local exit_code=$?
  trap - EXIT
  if [[ -n "${STAGING_DIR:-}" && -d "$STAGING_DIR" ]]; then
    case "$STAGING_DIR" in
      "$DESTINATION_REAL"/.sitara-backup-*)
        if ! rm -rf -- "$STAGING_DIR" 2>/dev/null ||
          [[ -e "$STAGING_DIR" || -L "$STAGING_DIR" ]]; then
          printf 'BACKUP_FAILED code=STAGING_CLEANUP_FAILED\n' >&2
          exit_code=1
        fi
        ;;
    esac
  fi
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

PLAINTEXT_ARCHIVE="${STAGING_DIR}/database.dump"
ENCRYPTED_ARCHIVE="${STAGING_DIR}/database.dump.age"
if ! MSYS_NO_PATHCONV=1 docker exec -i "$CONTAINER_ID" pg_dump \
  --host=/var/run/postgresql --port=5432 \
  --username "$DATABASE_USER" --dbname "$DATABASE" --format=custom \
  --no-owner --no-acl --file=- > "$PLAINTEXT_ARCHIVE" 2>/dev/null; then
  fail "PG_DUMP_FAILED"
fi
[[ -s "$PLAINTEXT_ARCHIVE" ]] || fail "EMPTY_ARCHIVE"

if ! docker exec -i "$CONTAINER_ID" pg_restore --list \
  < "$PLAINTEXT_ARCHIVE" >/dev/null 2>&1; then
  fail "ARCHIVE_VALIDATION_FAILED"
fi

PLAINTEXT_ARCHIVE_SIZE="$(stat -c '%s' -- "$PLAINTEXT_ARCHIVE" 2>/dev/null)" \
  || fail "ARCHIVE_SIZE_UNAVAILABLE"
[[ "$PLAINTEXT_ARCHIVE_SIZE" =~ ^[0-9]+$ ]] || fail "ARCHIVE_SIZE_UNVERIFIABLE"
PLAINTEXT_ARCHIVE_SHA256="$(sha256sum -- "$PLAINTEXT_ARCHIVE" | awk '{ print $1 }')" \
  || fail "ARCHIVE_CHECKSUM_FAILED"
[[ "$PLAINTEXT_ARCHIVE_SHA256" =~ ^[a-fA-F0-9]{64}$ ]] || fail "ARCHIVE_CHECKSUM_FAILED"

AVAILABLE_KB="$(df -Pk -- "$DESTINATION_REAL" 2>/dev/null | awk 'NR == 2 { print $4 }')" \
  || fail "DESTINATION_CAPACITY_UNAVAILABLE"
[[ "$AVAILABLE_KB" =~ ^[0-9]+$ ]] || fail "DESTINATION_CAPACITY_UNAVAILABLE"
REMAINING_REQUIRED_KB=$(((PLAINTEXT_ARCHIVE_SIZE + 1023) / 1024 + 16384))
(( AVAILABLE_KB >= REMAINING_REQUIRED_KB )) || fail "INSUFFICIENT_DESTINATION_CAPACITY"

if ! age --encrypt --recipient "$AGE_RECIPIENT" \
  --output "${ENCRYPTED_ARCHIVE}.partial" "$PLAINTEXT_ARCHIVE" 2>/dev/null; then
  fail "ENCRYPTION_FAILED"
fi
[[ -s "${ENCRYPTED_ARCHIVE}.partial" ]] || fail "EMPTY_ENCRYPTED_ARCHIVE"
mv -- "${ENCRYPTED_ARCHIVE}.partial" "$ENCRYPTED_ARCHIVE" \
  || fail "ENCRYPTED_ARCHIVE_FINALIZE_FAILED"
rm -f -- "$PLAINTEXT_ARCHIVE" || fail "PLAINTEXT_CLEANUP_FAILED"

ENCRYPTED_ARCHIVE_SIZE="$(stat -c '%s' -- "$ENCRYPTED_ARCHIVE" 2>/dev/null)" \
  || fail "ENCRYPTED_ARCHIVE_SIZE_UNAVAILABLE"
[[ "$ENCRYPTED_ARCHIVE_SIZE" =~ ^[0-9]+$ ]] || fail "ENCRYPTED_ARCHIVE_SIZE_UNVERIFIABLE"
ENCRYPTED_ARCHIVE_SHA256="$(sha256sum -- "$ENCRYPTED_ARCHIVE" | awk '{ print $1 }')" \
  || fail "ENCRYPTED_ARCHIVE_CHECKSUM_FAILED"
[[ "$ENCRYPTED_ARCHIVE_SHA256" =~ ^[a-fA-F0-9]{64}$ ]] \
  || fail "ENCRYPTED_ARCHIVE_CHECKSUM_FAILED"

COMPLETED_AT_UTC="$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || fail "UTC_CLOCK_UNAVAILABLE"
MANIFEST_FILE="${STAGING_DIR}/manifest.json"
ENCRYPTED_MANIFEST="${STAGING_DIR}/manifest.json.age"
cat > "$MANIFEST_FILE" <<EOF
{
  "backup_id": "${BACKUP_ID}",
  "status": "COMPLETE",
  "started_at_utc": "${STARTED_AT_UTC}",
  "completed_at_utc": "${COMPLETED_AT_UTC}",
  "source_environment": "${ENVIRONMENT}",
  "source_database": "${DATABASE}",
  "source_cluster_system_identifier": "${SOURCE_SYSTEM_IDENTIFIER}",
  "postgresql_server_version_num": "${SERVER_VERSION_NUM}",
  "pg_dump_version": "${PG_DUMP_VERSION_NUMBER}",
  "archive_format": "custom",
  "plaintext_archive_size_bytes": ${PLAINTEXT_ARCHIVE_SIZE},
  "plaintext_archive_sha256": "${PLAINTEXT_ARCHIVE_SHA256}",
  "encrypted_file": "database.dump.age",
  "encrypted_file_size_bytes": ${ENCRYPTED_ARCHIVE_SIZE},
  "encrypted_file_sha256": "${ENCRYPTED_ARCHIVE_SHA256}",
  "encryption": "age",
  "age_version": "${AGE_VERSION}"
}
EOF
if ! age --encrypt --recipient "$AGE_RECIPIENT" \
  --output "${ENCRYPTED_MANIFEST}.partial" "$MANIFEST_FILE" 2>/dev/null; then
  fail "MANIFEST_ENCRYPTION_FAILED"
fi
[[ -s "${ENCRYPTED_MANIFEST}.partial" ]] || fail "EMPTY_ENCRYPTED_MANIFEST"
mv -- "${ENCRYPTED_MANIFEST}.partial" "$ENCRYPTED_MANIFEST" \
  || fail "ENCRYPTED_MANIFEST_FINALIZE_FAILED"
rm -f -- "$MANIFEST_FILE" || fail "PLAINTEXT_MANIFEST_CLEANUP_FAILED"
ENCRYPTED_MANIFEST_SIZE="$(stat -c '%s' -- "$ENCRYPTED_MANIFEST" 2>/dev/null)" \
  || fail "ENCRYPTED_MANIFEST_SIZE_UNAVAILABLE"
[[ "$ENCRYPTED_MANIFEST_SIZE" =~ ^[0-9]+$ ]] || fail "ENCRYPTED_MANIFEST_SIZE_UNVERIFIABLE"
ENCRYPTED_MANIFEST_SHA256="$(sha256sum -- "$ENCRYPTED_MANIFEST" | awk '{ print $1 }')" \
  || fail "ENCRYPTED_MANIFEST_CHECKSUM_FAILED"
[[ "$ENCRYPTED_MANIFEST_SHA256" =~ ^[a-fA-F0-9]{64}$ ]] \
  || fail "ENCRYPTED_MANIFEST_CHECKSUM_FAILED"
printf '%s  %s\n' "$ENCRYPTED_ARCHIVE_SHA256" "database.dump.age" \
  > "${STAGING_DIR}/database.dump.age.sha256"
printf '%s  %s\n' "$ENCRYPTED_MANIFEST_SHA256" "manifest.json.age" \
  > "${STAGING_DIR}/manifest.json.age.sha256"

[[ ! -e "$FINAL_DIRECTORY" && ! -L "$FINAL_DIRECTORY" ]] || fail "BACKUP_DESTINATION_EXISTS"
if ! mv -T -n -- "$STAGING_DIR" "$FINAL_DIRECTORY" 2>/dev/null; then
  fail "ATOMIC_PUBLISH_FAILED"
fi
[[ ! -e "$STAGING_DIR" && -d "$FINAL_DIRECTORY" ]] || fail "ATOMIC_PUBLISH_COLLISION"
STAGING_DIR=""

printf 'BACKUP_COMPLETE id=%s encrypted_sha256=%s\n' "$BACKUP_ID" "$ENCRYPTED_ARCHIVE_SHA256"
