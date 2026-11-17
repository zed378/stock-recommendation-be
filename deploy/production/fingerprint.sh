#!/bin/sh
# A comparable, secret-free fingerprint of an AIDSS installation (read-only).
#
#   sh fingerprint.sh > fingerprint-old.txt     # on the old host, before the final dump
#   sh fingerprint.sh > fingerprint-new.txt     # on the new host, after the restore
#   diff fingerprint-old.txt fingerprint-new.txt  # empty means the data and the secrets moved intact
#
# It prints counts, versions, role names, the Trader's trading state, and SHORT HASHES of the two secrets that must
# move byte for byte (the JWT secret and the Trader master key), so equality can be shown without anything secret
# being printed. It reads the database as the superuser over the container's local socket (no password) and the
# JWT secret from the `.env` named in AIDSS_ENV_FILE (or, failing that, the running api container); it changes nothing.
#
# Container names default to the Compose project `stocks`; override for another project name.
set -eu

PG=${AIDSS_PG_CONTAINER:-stocks-postgres-1}
API=${AIDSS_API_CONTAINER:-stocks-api-1}
KEY_FILE=${AIDSS_TRADER_MASTER_KEY_PATH:-$HOME/.aidss-trader-master.key}
DB=${AIDSS_DB_NAME:-aidss}

q() { docker exec -i "$PG" psql -U aidss -d "$DB" -At -v ON_ERROR_STOP=1 -c "$1"; }
short() { sha256sum | cut -c1-12; }

echo "postgres_version=$(q 'show server_version' | cut -d' ' -f1)"
echo "vector_extension=$(q "select coalesce((select extversion from pg_extension where extname = 'vector'), 'absent')")"
echo "alembic_public=$(q 'select coalesce(string_agg(version_num, $$,$$ order by version_num), $$none$$) from public.alembic_version' 2>/dev/null || echo missing)"
echo "alembic_trading=$(q 'select coalesce(string_agg(version_num, $$,$$ order by version_num), $$none$$) from trading.alembic_version' 2>/dev/null || echo missing)"
echo "roles=$(q "select string_agg(rolname || '(' || case when rolsuper then 'S' else '-' end || case when rolcanlogin then 'L' else '-' end || ')', ',' order by rolname) from pg_roles where rolname !~ '^pg_'")"
echo "trading_state=$(q 'select state from trading.trading_state' 2>/dev/null | head -1 || true)"
echo "audit_head=$(q 'select coalesce(max(seq)::text, $$empty$$) from trading.audit_log' 2>/dev/null || echo missing)"

echo "-- row counts (base tables)"
docker exec -i "$PG" psql -U aidss -d "$DB" -At -v ON_ERROR_STOP=1 <<'SQL'
select table_schema || '.' || table_name || '=' ||
  (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
from information_schema.tables
where table_schema not in ('pg_catalog', 'information_schema') and table_type = 'BASE TABLE'
order by 1;
SQL

echo "-- secrets (first 12 hex of sha256; equal on both hosts or the move was not byte for byte)"
# The .env wins when given: it exists on both hosts whether or not the api container is up, and it is what the stack
# is started from. Otherwise the running api container's environment is read.
jwt=""
if [ -n "${AIDSS_ENV_FILE:-}" ] && [ -r "$AIDSS_ENV_FILE" ]; then
    jwt=$(sed -n 's/^AIDSS_JWT_SECRET=//p' "$AIDSS_ENV_FILE" | head -n 1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//")
elif ! jwt=$(docker exec "$API" printenv AIDSS_JWT_SECRET 2>/dev/null); then
    jwt=""
fi
if [ -n "$jwt" ]; then
    echo "jwt_secret_sha256_12=$(printf '%s' "$jwt" | short)"
else
    echo "jwt_secret_sha256_12=unavailable (no AIDSS_ENV_FILE and the api container is not running)"
fi
if [ -r "$KEY_FILE" ]; then
    echo "trader_master_key_sha256_12=$(cat "$KEY_FILE" | short)"
else
    echo "trader_master_key_sha256_12=unavailable ($KEY_FILE not readable)"
fi
