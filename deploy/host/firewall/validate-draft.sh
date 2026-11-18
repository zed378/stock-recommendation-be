#!/bin/sh
# Developer-only check in a disposable network namespace; never loads host rules.
set -eu
IMAGE=aidss-nft-validator:alpine3.22.2
if [ "${1:-}" = --prepare ]; then
    # Only this explicit preparation step downloads packages; validation stays offline.
    exec docker build --tag "$IMAGE" - <<'DOCKER'
FROM alpine:3.22.2
RUN apk add --no-cache nftables
DOCKER
fi
if [ "${1:-}" = --help ]; then
    printf '%s\n' 'Usage: sh validate-draft.sh [draft.nft]' \
        'Run --prepare once to build local aidss-nft-validator:alpine3.22.2 (downloads packages).' \
        'The normal check performs no downloads, builds, or host firewall actions.'
    exit 0
fi
[ "$#" -le 1 ] || { printf '%s\n' 'Expected at most one draft path' >&2; exit 3; }
DRAFT=${1:-$(dirname "$0")/docker-user.nft}
[ -f "$DRAFT" ] || { printf '%s\n' 'Draft file missing' >&2; exit 3; }
DRAFT=$(cd "$(dirname "$DRAFT")" && pwd)/$(basename "$DRAFT")
command -v docker >/dev/null 2>&1 || { printf '%s\n' 'Docker unavailable' >&2; exit 3; }
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    printf '%s\n' 'NOT VALIDATED: local validator image missing; see operations document 08.' >&2
    exit 3
fi
# Prevent Git Bash from rewriting the container mount destination/arguments.
export MSYS_NO_PATHCONV=1
if command -v cygpath >/dev/null 2>&1; then DRAFT=$(cygpath -am "$DRAFT"); fi
exec docker run --rm --pull never --cap-drop ALL --cap-add NET_ADMIN \
    --security-opt no-new-privileges --network none --read-only \
    --mount "type=bind,source=$DRAFT,target=/draft.nft,readonly" \
    "$IMAGE" sh -c 'nft --version && uname -r && nft -c -f /draft.nft'
