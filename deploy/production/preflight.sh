#!/bin/sh
# Read-only checks on a NEW host before anything is restored or started.
#
#   sh preflight.sh [path/to/.env] [path/to/docker-compose.production.yml]
#
# Prints PASS, WARN or FAIL per check and exits 1 if any FAIL. It reads the .env as text (it never sources it, so a
# value is never executed or printed) and touches nothing.
set -u

ENV_FILE=${1:-.env}
COMPOSE=${2:-docker-compose.production.yml}
fails=0
pass() { echo "PASS  $*"; }
warn() { echo "WARN  $*"; }
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }

val() { sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | head -n 1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"; }

# --- the machine
command -v docker >/dev/null 2>&1 && pass "docker: $(docker --version | cut -c1-60)" || fail "docker is not installed"
docker compose version >/dev/null 2>&1 && pass "compose: $(docker compose version | cut -c1-60)" || fail "docker compose (v2) is not available"
arch=$(uname -m)
case $arch in
    x86_64|amd64) pass "architecture $arch (the published images are linux/amd64)" ;;
    *) warn "architecture $arch: the published images are linux/amd64 only; build multi-arch images before moving here" ;;
esac
avail=$(df -Pk . | awk 'NR==2 {print int($4/1024/1024)}')
[ "${avail:-0}" -ge 5 ] && pass "free disk here: ${avail} GB" || fail "free disk here: ${avail:-?} GB (need at least 5, more for dumps)"
if command -v timedatectl >/dev/null 2>&1; then
    timedatectl 2>/dev/null | grep -qi 'synchronized: yes' && pass "clock synchronized (the Trader halts on skew over 250 ms)" \
        || fail "clock is not synchronized: fix NTP first (ADR-041)"
else
    warn "timedatectl not found: confirm NTP is running by hand (the Trader halts on skew over 250 ms)"
fi
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ':5173$'; then
    fail "port 5173 is already in use on this host"
else
    pass "port 5173 is free"
fi
docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^stocks-' && fail "containers of a project named stocks are already running here" || pass "no stocks-* container is running yet"

# --- the .env
if [ ! -f "$ENV_FILE" ]; then
    fail "$ENV_FILE not found"
else
    mode=$(stat -c %a "$ENV_FILE" 2>/dev/null || echo '?')
    [ "$mode" = "600" ] && pass "$ENV_FILE mode 600" || fail "$ENV_FILE mode is $mode (want 600)"
    for name in AIDSS_JWT_SECRET POSTGRES_PASSWORD AIDSS_APP_DATABASE_URL AIDSS_TRADER_DATABASE_URL \
        AIDSS_TRADER_MASTER_KEY_PATH AIDSS_API_IMAGE AIDSS_FRONTEND_IMAGE AIDSS_TRADER_IMAGE; do
        [ -n "$(val "$name")" ] && pass "$name is set" || fail "$name is empty or missing in $ENV_FILE"
    done
    jwt=$(val AIDSS_JWT_SECRET)
    [ "${#jwt}" -ge 32 ] && pass "AIDSS_JWT_SECRET length ${#jwt}" || fail "AIDSS_JWT_SECRET is shorter than 32 characters"
    case $(val AIDSS_TRADER_IMAGE) in
        *:latest|"") fail "AIDSS_TRADER_IMAGE must be a commit tag or digest, never latest (ADR-053)" ;;
        *) pass "AIDSS_TRADER_IMAGE is pinned" ;;
    esac
    case $(val AIDSS_APP_DATABASE_URL) in
        *://aidss:*) fail "AIDSS_APP_DATABASE_URL uses the superuser; the analysis stack must use aidss_app (ADR-021)" ;;
        *) pass "AIDSS_APP_DATABASE_URL is not the superuser" ;;
    esac
    key=$(val AIDSS_TRADER_MASTER_KEY_PATH)
    if [ -f "$key" ]; then
        kmode=$(stat -c %a "$key" 2>/dev/null || echo '?')
        ksize=$(wc -c <"$key" | tr -d ' ')
        [ "$kmode" = "600" ] && pass "master key file mode 600" || fail "master key file mode is $kmode (want 600)"
        [ "$ksize" -ge 44 ] && [ "$ksize" -le 45 ] && pass "master key file is $ksize bytes" \
            || warn "master key file is $ksize bytes (a generated key is 44)"
    else
        fail "master key file not found at AIDSS_TRADER_MASTER_KEY_PATH (copy it from the old host over a separate channel)"
    fi
fi

# --- the compose file and the registry
if docker compose --env-file "$ENV_FILE" -f "$COMPOSE" config >/dev/null 2>/tmp/aidss-preflight.err; then
    pass "$COMPOSE resolves with this .env"
else
    fail "$COMPOSE does not resolve: $(tail -1 /tmp/aidss-preflight.err | cut -c1-120)"
fi
rm -f /tmp/aidss-preflight.err
for var in AIDSS_API_IMAGE AIDSS_FRONTEND_IMAGE AIDSS_TRADER_IMAGE; do
    img=$(val "$var")
    [ -z "$img" ] && continue
    docker manifest inspect "$img" >/dev/null 2>&1 && pass "$img can be pulled" || fail "$img cannot be found in the registry from here"
done

echo
[ "$fails" -eq 0 ] && echo "preflight: no FAIL" || echo "preflight: $fails FAIL"
[ "$fails" -eq 0 ]
