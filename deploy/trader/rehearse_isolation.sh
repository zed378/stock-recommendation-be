#!/usr/bin/env sh
# T1/T6 — Non-destructive host-hardening & `aidss_app` isolation rehearsal (ADR-021).
#
# Clones the target database into a temporary scratch database via `pg_dump | psql`,
# applies `deploy/trader/isolate_analysis_role.sql`, sets a random temporary password
# for `aidss_app` over stdin (never in CLI arguments), verifies role attributes,
# `public` ownership, and denial of `schema trading` access via `SET ROLE aidss_app`,
# measures `rollback_analysis_role.sql` elapsed time, and drops both the scratch
# database and the cluster-wide `aidss_app` role (if created by this script) on exit.
#
# Usage (after owner approval):
#   sh deploy/trader/rehearse_isolation.sh [postgres-container] [db-user] [source-db]

set -eu

CONTAINER="${1:-stocks-postgres-1}"
PG_USER="${2:-aidss}"
SOURCE_DB="${3:-aidss}"
SCRATCH_DB="aidss_role_rehearsal_$(date +%s)"
DUMP_FILE="/tmp/${SCRATCH_DB}.sql"
CREATED_APP_ROLE=0

cleanup() {
  rm -f "$DUMP_FILE"
  docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=0 \
    -c "DROP DATABASE IF EXISTS ${SCRATCH_DB} WITH (FORCE);" >/dev/null || true
  if [ "$CREATED_APP_ROLE" -eq 1 ]; then
    docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=0 \
      -c "DROP ROLE IF EXISTS aidss_app;" >/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

ROLE_EXISTS="$(docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname = 'aidss_app';" | tr -d '[:space:]')"
if [ "$ROLE_EXISTS" != "1" ]; then
  CREATED_APP_ROLE=1
fi

echo "[1/6] Cloning ${SOURCE_DB} into scratch database ${SCRATCH_DB}..."
CLONE_START="$(date +%s)"
docker exec "$CONTAINER" pg_dump -U "$PG_USER" -d "$SOURCE_DB" > "$DUMP_FILE"
docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE ${SCRATCH_DB};" >/dev/null
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 < "$DUMP_FILE" >/dev/null
rm -f "$DUMP_FILE"
CLONE_END="$(date +%s)"
echo "  Clone completed in $((CLONE_END - CLONE_START))s."

echo "[2/6] Applying deploy/trader/isolate_analysis_role.sql..."
ISO_START="$(date +%s)"
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 \
  < deploy/trader/isolate_analysis_role.sql >/dev/null
ISO_END="$(date +%s)"
echo "  Isolation applied in $((ISO_END - ISO_START))s."

echo "[3/6] Assigning random temporary password to aidss_app via stdin..."
TMP_PW="$(dd if=/dev/urandom bs=24 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
printf "ALTER ROLE aidss_app PASSWORD '%s';\n" "$TMP_PW" | \
  docker exec -i "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 >/dev/null
unset TMP_PW

echo "[4/6] Verifying aidss_app attributes and public ownership..."
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
  FROM pg_roles WHERE rolname = 'aidss_app';
SELECT count(*) AS public_tables_not_owned_by_aidss_app
  FROM pg_tables
 WHERE schemaname = 'public' AND tableowner <> 'aidss_app';
"

echo "[5/6] Verifying SQL access boundaries as SET ROLE aidss_app..."
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
BEGIN;
SET LOCAL ROLE aidss_app;
CREATE TABLE public._rehearsal_probe (id int);
DROP TABLE public._rehearsal_probe;
COMMIT;
" >/dev/null
if docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
BEGIN;
SET LOCAL ROLE aidss_app;
SELECT 1 FROM trading.audit_log LIMIT 1;
ROLLBACK;
" >/dev/null 2>&1; then
  echo "ERROR: aidss_app was able to read trading.audit_log!" >&2
  exit 1
fi
echo "  Verified: public DDL ok, trading.audit_log denied for aidss_app."

echo "[6/6] Running and timing deploy/trader/rollback_analysis_role.sql..."
RB_START="$(date +%s)"
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 \
  < deploy/trader/rollback_analysis_role.sql >/dev/null
RB_END="$(date +%s)"
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS public_tables_not_owned_by_superuser
  FROM pg_tables
 WHERE schemaname = 'public' AND tableowner <> '${PG_USER}';
"
echo "Isolation rehearsal completed cleanly (isolate=$((ISO_END - ISO_START))s, rollback=$((RB_END - RB_START))s)."
