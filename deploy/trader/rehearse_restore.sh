#!/usr/bin/env sh
# T6-03 — Non-destructive restore rehearsal for the `trading` schema (ADR-040).
#
# Owner-led rehearsal helper. Dumps `schema trading` from the source database,
# restores it into a temporary scratch database on the same PostgreSQL container,
# verifies table presence, row counts, and the `trader_rw` append-only privilege
# boundary, prints the elapsed duration in seconds for the release record, and
# drops the scratch database on exit.
#
# Usage on the VM (after owner approval):
#   sh deploy/trader/rehearse_restore.sh [--full] [postgres-container] [db-user] [source-db]

set -eu
# The dump holds the whole database (password hashes, encrypted credentials). Owner-only files,
# so no other user on the shared host can read it while the script runs.
umask 077

FULL_MODE=0
if [ "${1:-}" = "--full" ]; then
  FULL_MODE=1
  shift
fi

CONTAINER="${1:-stocks-postgres-1}"
PG_USER="${2:-aidss}"
SOURCE_DB="${3:-aidss}"
SCRATCH_DB="aidss_restore_rehearsal_$(date +%s)"
DUMP_FILE="/tmp/${SCRATCH_DB}.sql"

cleanup() {
  rm -f "$DUMP_FILE"
  docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=0 \
    -c "DROP DATABASE IF EXISTS ${SCRATCH_DB} WITH (FORCE);" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

START_TS="$(date +%s)"
if [ "$FULL_MODE" -eq 1 ]; then
  echo "[1/5] Dumping FULL database ${SOURCE_DB}..."
  docker exec "$CONTAINER" pg_dump -U "$PG_USER" -d "$SOURCE_DB" > "$DUMP_FILE"
else
  echo "[1/5] Dumping schema 'trading' from ${SOURCE_DB}..."
  docker exec "$CONTAINER" pg_dump -U "$PG_USER" -d "$SOURCE_DB" -n trading > "$DUMP_FILE"
fi

echo "[2/5] Creating scratch database ${SCRATCH_DB} and bootstrapping roles..."
docker exec "$CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE ${SCRATCH_DB};"
sed "s/<database>/${SCRATCH_DB}/g" deploy/trader/bootstrap.sql | \
  docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1

if [ "$FULL_MODE" -eq 1 ]; then
  echo "[3/5] Restoring FULL database into ${SCRATCH_DB}..."
else
  echo "[3/5] Restoring schema 'trading' into ${SCRATCH_DB}..."
fi
docker exec -i "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 < "$DUMP_FILE"

echo "[4/5] Verifying restored tables and row counts..."
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
SELECT table_schema, count(*) AS table_count
  FROM information_schema.tables
 WHERE table_schema IN ('public', 'trading')
 GROUP BY table_schema
 ORDER BY table_schema;
SELECT table_name
  FROM information_schema.tables
 WHERE table_schema = 'trading'
 ORDER BY table_name;
SELECT 'audit_log' AS table_name, count(*) AS rows FROM trading.audit_log
UNION ALL
SELECT 'ledger_entry', count(*) FROM trading.ledger_entry
UNION ALL
SELECT 'risk_limit', count(*) FROM trading.risk_limit
UNION ALL
SELECT 'strategy', count(*) FROM trading.strategy;
"

echo "[5/5] Verifying append-only privilege boundary for trader_rw and trader_monitor..."
docker exec "$CONTAINER" psql -U "$PG_USER" -d "$SCRATCH_DB" -v ON_ERROR_STOP=1 -c "
SELECT
  has_table_privilege('trader_rw', 'trading.audit_log', 'UPDATE') AS rw_can_update_audit,
  has_table_privilege('trader_rw', 'trading.audit_log', 'DELETE') AS rw_can_delete_audit,
  has_table_privilege('trader_rw', 'trading.ledger_entry', 'UPDATE') AS rw_can_update_ledger,
  has_table_privilege('trader_monitor', 'trading.lease', 'SELECT') AS monitor_can_select_lease,
  has_table_privilege('trader_monitor', 'trading.lease', 'UPDATE') AS monitor_can_update_lease,
  has_table_privilege('trader_monitor', 'trading.credential', 'SELECT') AS monitor_can_select_cred;
"

END_TS="$(date +%s)"
ELAPSED="$((END_TS - START_TS))"
echo "Restore rehearsal completed cleanly in ${ELAPSED}s (scratch DB ${SCRATCH_DB} will now be dropped)."
