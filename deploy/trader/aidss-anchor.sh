#!/bin/sh
# Hourly external anchor of the Trader's audit-log head hash (ADR-054, T1-05).
#
# Runs `python -m aidss_trader audit-anchor` in a throw-away container, so the anchor file lives on the
# host, outside the database volume and outside the Trader container (which is read-only). Each run first
# verifies the chain and the previous anchor, so a truncated or rewritten audit log shows up as a non-zero
# exit (2 = the chain is broken) and a line in the log and in syslog; it does not need a second command.
#
# Only AIDSS_TRADER_DATABASE_URL (the Trader's own role, which can read the audit log) is read from the
# env file and handed on: the owner and monitor URLs in the same file never reach the container.
# Install: see MEMORY/records/2026-11-16-host-backup-pg-dumpall.md (step 7). Nothing here sends anything
# to an exchange or to Telegram.
set -u

ENV_FILE=${AIDSS_ANCHOR_ENV_FILE:-/home/infra/.aidss-trader.env}
DIR=${AIDSS_ANCHOR_DIR:-/var/lib/aidss-anchor}
IMAGE=${AIDSS_ANCHOR_IMAGE:-zed378/aidss-trader:7d03693}
NETWORK=${AIDSS_ANCHOR_NETWORK:-stocks_default}
RUN_AS=${AIDSS_ANCHOR_USER:-1000:1000}
LOG="$DIR/anchor.log"

note() { # severity, message
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $2"
    printf '%s\n' "$line" >>"$LOG" 2>/dev/null || true
    command -v logger >/dev/null 2>&1 && logger -t aidss-anchor -p "user.$1" -- "$2"
}

URL=$(sed -n 's/^AIDSS_TRADER_DATABASE_URL=//p' "$ENV_FILE" 2>/dev/null | head -n 1)
case $URL in
    \"*\") URL=${URL#\"}; URL=${URL%\"} ;;
    \'*\') URL=${URL#\'}; URL=${URL%\'} ;;
esac
if [ -z "$URL" ]; then
    note err "AIDSS_TRADER_DATABASE_URL not found in $ENV_FILE; nothing anchored"
    exit 3
fi
export AIDSS_TRADER_DATABASE_URL="$URL"

out=$(docker run --rm --network "$NETWORK" --user "$RUN_AS" --read-only --cap-drop ALL \
    --security-opt no-new-privileges -e AIDSS_TRADER_DATABASE_URL -v "$DIR:/anchor" \
    "$IMAGE" python -m aidss_trader audit-anchor --out /anchor/anchor.jsonl 2>&1)
rc=$?
# The program prints a hash and a path, never a credential; the first line is enough for a log.
first=$(printf '%s' "$out" | head -n 1 | cut -c1-300)
if [ "$rc" -eq 0 ]; then
    note info "rc=0 $first"
else
    note err "rc=$rc $first"
fi
exit "$rc"
