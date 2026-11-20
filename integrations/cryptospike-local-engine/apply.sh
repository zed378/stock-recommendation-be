#!/usr/bin/env bash
# Menerapkan mesin strategi lokal ke salinan repo cryptospike-client milik Anda.
#   ./apply.sh /path/ke/cryptospike-client
# Hanya MENAMBAH berkas dan mengubah satu berkas (server/src/index.ts, dua baris). Tidak menjalankan
# apa pun, tidak mengubah database, dan tidak menyalakan mesin (LOCAL_ENGINE_ENABLED=false bawaan).
set -euo pipefail
target="${1:?usage: apply.sh /path/to/cryptospike-client}"
here="$(cd "$(dirname "$0")" && pwd)"
[ -f "$target/server/src/index.ts" ] || { echo "not a cryptospike-client checkout: $target" >&2; exit 1; }
[ -e "$target/server/src/engine" ] && { echo "server/src/engine already exists; refusing to overwrite" >&2; exit 1; }
(cd "$target" && git apply --check "$here/index.ts.patch")
mkdir -p "$target/server/src/engine" "$target/server/src/services" "$target/server/tests"
cp "$here"/files/server/src/engine/*.ts "$target/server/src/engine/"
cp "$here"/files/server/src/services/local-engine.service.ts "$target/server/src/services/"
cp "$here"/files/server/tests/local-engine-*.test.ts "$target/server/tests/"
cp "$here/files/.env.local-engine.example" "$target/.env.local-engine.example"
(cd "$target" && git apply "$here/index.ts.patch")
echo "Applied. Next: cd server && npx tsx --test tests/local-engine-*.test.ts"
