#!/bin/sh
# Put the EODHD key, the fundamentals provider and the daily allowance into the AIDSS .env on the
# host. Run it yourself on the VM; the key is typed at a prompt that does not echo.
#
#   sh set-eodhd-key.sh
#
# The key is never an argument, never exported, never printed: it is read into a shell variable and
# written with the printf builtin. The previous file is copied to $HOME first (mode 600), because
# the directory holding .env is root-owned and the backup cannot sit beside it.
# It edits the file in place (the file is writable by its owner, the directory is not), changes
# only three names, keeps every other line, and does not restart anything: the containers must be
# recreated afterwards (api and worker, `--no-deps`).
set -eu
umask 077
ENV_FILE=${AIDSS_ENV_FILE:-/home/infra/stocks/.env}
[ -w "$ENV_FILE" ] || { echo "cannot write $ENV_FILE" >&2; exit 1; }

printf 'EODHD API key (not shown): '
stty -echo 2>/dev/null || true
IFS= read -r KEY
stty echo 2>/dev/null || true
printf '\n'
[ -n "$KEY" ] || { echo "no key entered; nothing changed" >&2; exit 1; }
case $KEY in *[!A-Za-z0-9._-]*) echo "the key has characters a token does not; nothing changed" >&2; exit 1 ;; esac

printf 'Daily fundamentals allowance from your plan (whole number; one request costs 10 calls, 0 = no ceiling): '
IFS= read -r QUOTA
case $QUOTA in '' | *[!0-9]*) echo "the allowance must be a whole number; nothing changed" >&2; exit 1 ;; esac

BACKUP="$HOME/.env.aidss-$(date -u +%Y%m%dT%H%M%SZ).bak"
cp -p "$ENV_FILE" "$BACKUP"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
while IFS= read -r line || [ -n "$line" ]; do
    case $line in
        AIDSS_EODHD_API_KEY=* | AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=* | AIDSS_FUNDAMENTALS_DAILY_QUOTA=*) ;;
        *) printf '%s\n' "$line" >>"$TMP" ;;
    esac
done <"$ENV_FILE"
printf 'AIDSS_EODHD_API_KEY=%s\n' "$KEY" >>"$TMP"
printf 'AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd\n' >>"$TMP"
printf 'AIDSS_FUNDAMENTALS_DAILY_QUOTA=%s\n' "$QUOTA" >>"$TMP"
cat "$TMP" >"$ENV_FILE"
unset KEY
echo "updated $ENV_FILE (backup: $BACKUP)"
echo "names now set: AIDSS_EODHD_API_KEY, AIDSS_COMPOSITE_FUNDAMENTALS_PROVIDER=eodhd, AIDSS_FUNDAMENTALS_DAILY_QUOTA=$QUOTA"
echo "Next: tell the agent to recreate api and worker, or run the usual --no-deps deploy."
