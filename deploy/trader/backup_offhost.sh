#!/usr/bin/env bash
# Stream the cluster dump into encryption; no plaintext backup is materialized.
set +x
set -Eeuo pipefail
umask 077

HOST=infra@10.1.200.13
DEST="$HOME/aidss-offhost-backups"
PASS_FD=
SOURCE_CMD=
OUT_FILE=
SHA_FILE=
OWN_OUT=0
OWN_SHA=0
SUCCESS=0
PASSPHRASE=
unset PASSPHRASE
# An inherited exported variable must not turn the passphrase into an environment value.
declare PASSPHRASE=

usage() {
    cat <<'EOF'
Usage: bash deploy/trader/backup_offhost.sh [--dest DIR] [--host USER@HOST]
       [--passphrase-fd N] [--source-cmd CMD]
Use Git Bash or POSIX Bash only, not PowerShell binary pipelines.
Default destination: $HOME/aidss-offhost-backups (created with umask 077).
Passphrase is prompted twice, silently, and passed to OpenSSL through a pipe FD.
--passphrase-fd N reads one newline-terminated passphrase from an already open FD.
--source-cmd CMD replaces SSH with a local Bash command FOR TESTS ONLY.
No restore is performed. Keep the master key separate from every backup.
EOF
}
fail() { printf '%s\n' "$1" >&2; exit 1; }
cleanup() {
    unset PASSPHRASE CONFIRM
    if [ "$SUCCESS" -ne 1 ]; then
        [ "$OWN_OUT" -ne 1 ] || rm -f -- "$OUT_FILE"
        [ "$OWN_SHA" -ne 1 ] || rm -f -- "$SHA_FILE"
    fi
    return 0
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dest|--host|--passphrase-fd|--source-cmd)
            [ "$#" -ge 2 ] || fail 'Missing option value'
            case "$1" in
                --dest) DEST=$2 ;;
                --host) HOST=$2 ;;
                --passphrase-fd) PASS_FD=$2 ;;
                --source-cmd) SOURCE_CMD=$2 ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) fail 'Unknown option (see --help)' ;;
    esac
done
[ -n "$DEST" ] || fail 'Destination must not be empty'
case "$HOST" in -*) fail 'Invalid SSH target' ;; esac
for cmd in gzip awk sha256sum bash; do
    command -v "$cmd" >/dev/null || fail "Missing command: $cmd"
done
# Git for Windows also ships a native OpenSSL that cannot read MSYS pipe FDs.
if [ -x /usr/bin/openssl ]; then OPENSSL_BIN=/usr/bin/openssl
else OPENSSL_BIN=$(command -v openssl) || fail 'Missing command: openssl'; fi
if [ -z "$SOURCE_CMD" ]; then command -v ssh >/dev/null || fail 'Missing command: ssh'; fi
if [ -n "$PASS_FD" ]; then
    [[ "$PASS_FD" =~ ^[0-9]+$ ]] || fail 'Passphrase FD must be numeric'
    IFS= read -r -u "$PASS_FD" PASSPHRASE || fail 'Cannot read passphrase FD'
else
    unset CONFIRM
    IFS= read -r -s -p 'Backup passphrase: ' PASSPHRASE </dev/tty || fail 'Cannot read terminal'
    printf '\n' >/dev/tty
    IFS= read -r -s -p 'Confirm passphrase: ' CONFIRM </dev/tty || fail 'Cannot read terminal'
    printf '\n' >/dev/tty
    [ "$PASSPHRASE" = "$CONFIRM" ] || fail 'Passphrases do not match'
    unset CONFIRM
fi
[ -n "$PASSPHRASE" ] || fail 'Passphrase must not be empty'

mkdir -p -- "$DEST"
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_FILE="$DEST/aidss-pg_dumpall-$TS.sql.gz.enc"
SHA_FILE="$OUT_FILE.sha256"
# noclobber claims each path atomically, including refusing existing symlinks.
set -C
if ! exec 4>"$OUT_FILE"; then fail 'Refusing to overwrite backup'; fi
OWN_OUT=1
if ! exec 5>"$SHA_FILE"; then fail 'Refusing to overwrite checksum'; fi
OWN_SHA=1
chmod 600 -- "$OUT_FILE" "$SHA_FILE"

source_stream() {
    if [ -n "$SOURCE_CMD" ]; then
        bash -o pipefail -c "$SOURCE_CMD"
    else
        # Fixed remote string: the target is an SSH argument, never interpolated into shell code.
        ssh -n "$HOST" "bash -o pipefail -c 'docker exec stocks-postgres-1 pg_dumpall -U aidss --quote-all-identifiers | gzip -6'"
    fi
}
# printf is a Bash builtin in a pipe-backed process substitution, not an external argv.
source_stream | "$OPENSSL_BIN" enc -aes-256-cbc -pbkdf2 -iter 600000 -salt \
    -pass fd:3 3< <(builtin printf '%s\n' "$PASSPHRASE") >&4 || fail 'Backup stream failed'
exec 4>&-

decrypt() {
    "$OPENSSL_BIN" enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
        -pass fd:3 -in "$OUT_FILE" 3< <(builtin printf '%s\n' "$PASSPHRASE")
}
decrypt | gzip -t || fail 'Compressed archive verification failed'
SUMMARY=$(decrypt | gzip -dc | awk '
    BEGIN { roles=0; copies=0; bytes=0; complete=0; in_copy=0 }
    {
        bytes += length($0)+1
        if (in_copy) {
            if ($0 == "\\.") in_copy=0
            next
        }
        if ($0 ~ /^CREATE ROLE /) roles++
        if ($0 ~ /^COPY .* FROM stdin;$/) { copies++; in_copy=1 }
        if ($0 == "-- PostgreSQL database cluster dump complete") complete=1
        else if (complete && $0 !~ /^[[:space:]]*$/ && $0 !~ /^--/) complete=0
    }
    END {
        if (!complete || in_copy || roles<1 || bytes<64) exit 1
        printf "roles=%d copy_blocks=%d bytes=%d\n", roles, copies, bytes
    }
') || fail 'Dump structure verification failed'
(cd -- "$DEST" && sha256sum -- "${OUT_FILE##*/}") >&5
exec 5>&-
SUCCESS=1
printf 'Backup: %s\nChecksum: %s\nVerified: %s\n' "$OUT_FILE" "$SHA_FILE" "$SUMMARY"
printf '%s\n' 'Restore example ONLY; replace SCRATCH_CONTAINER with an isolated rehearsal container:'
printf 'openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in %q | gunzip | docker exec -i SCRATCH_CONTAINER psql -U postgres\n' "$OUT_FILE"
printf '%s\n' 'See runbook R9 and deploy/trader/rehearse_restore.sh. Nothing was restored.'
