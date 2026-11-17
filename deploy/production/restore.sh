#!/bin/sh
# Restore a `pg_dumpall` of AIDSS into a FRESH PostgreSQL container, from standard input.
#
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in dump.sql.gz.enc | gunzip | sh restore.sh
#
# The plain SQL travels in a pipe and is never written to disk. Run it with only `postgres` up:
#   docker compose -f docker-compose.production.yml up -d postgres
# because the api runs `alembic upgrade head` when it starts, and a restore over tables it just created fails.
#
# Refuses unless: the postgres container is running; no app container (api, worker, trader, frontend) is running;
# and the target database has no table in `public` or `trading`. `--force` skips the last check only; it never
# skips the app-container check, because restoring under a running Trader is how two writers meet.
#
# The only errors it tolerates are "already exists" (the dump recreates the `aidss` role and database that the image
# already made; the role's password hash from the dump then replaces the initial one, which is intended).
set -eu

PG=${AIDSS_PG_CONTAINER:-stocks-postgres-1}
APPS=${AIDSS_APP_CONTAINERS:-stocks-api-1 stocks-worker-1 stocks-trader-1 stocks-frontend-1}
DB=${AIDSS_DB_NAME:-aidss}
FORCE=no
[ "${1:-}" = "--force" ] && FORCE=yes

die() { echo "restore: $*" >&2; exit 1; }

[ -t 0 ] && die "no dump on standard input (pipe the decrypted, gunzipped dump in)"
docker ps --format '{{.Names}}' | grep -qx "$PG" || die "container $PG is not running"
for app in $APPS; do
    docker ps --format '{{.Names}}' | grep -qx "$app" && die "$app is running: stop the application containers first"
done

tables=$(docker exec "$PG" psql -U aidss -d "$DB" -At -c \
    "select count(*) from information_schema.tables where table_schema in ('public','trading')")
if [ "$tables" != "0" ] && [ "$FORCE" != "yes" ]; then
    die "database $DB already holds $tables tables; refusing to restore over them (use --force only on a scratch database)"
fi

errors=$(mktemp)
trap 'rm -f "$errors"' EXIT
# ON_ERROR_STOP off on purpose: the benign "already exists" lines must not stop the restore.
docker exec -i "$PG" psql -U aidss -d postgres -q -v ON_ERROR_STOP=0 -o /dev/null 2>"$errors" || true

unexpected=$(grep -ci 'error' "$errors" || true)
benign=$(grep -ci 'already exists' "$errors" || true)
echo "restore: stderr lines with 'error': $unexpected, of which 'already exists': $benign"
if [ "$unexpected" -gt "$benign" ]; then
    echo "restore: errors other than 'already exists':" >&2
    grep -i 'error' "$errors" | grep -vi 'already exists' | head -10 >&2
    exit 1
fi
echo "restore: done. Next: sh fingerprint.sh, compare with the old host's, then start the other services one at a time with --no-deps."
