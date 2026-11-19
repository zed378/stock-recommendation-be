# Audit-anchor wrapper: no more pinned image (2026-11-19)

Owner's request: repoint the host wrapper at a tag the registry keeps, so `aidss-trader:7d03693` (kept only for it) can go.

Instead of swapping one pinned tag for another, which would go stale at the next deploy, `deploy/trader/aidss-anchor.sh` now chooses its image in this order: `AIDSS_ANCHOR_IMAGE` if set (refused with exit 3 when it is not a plain image reference), else the image the running Trader container was started from (`docker inspect` of `stocks-trader-1`, validated the same way; always present on the host and the version that writes the audit log), else `zed378/aidss-trader:latest` when no Trader is running, so an outage does not stop the anchoring. The log line now ends with `image=<reference>`; the freshness watcher's pattern (`^<time> rc=<n>`) is unaffected. Tests: 4 new in `tests/trader/test_aidss_anchor_script.py` (running image used, fallback with no Trader, an odd name refused, explicit image wins and a bad one starts nothing); 16 passed with the watcher's tests.

Installed on the host (`infra` over SSH, `sudo`): the previous file kept as `/usr/local/bin/aidss-anchor.bak-20261119`, the new one installed root-owned mode 755 (sha256 `8f795220...`), syntax-checked, then run once by hand as the cron user: `rc=0`, `anchored seq=39`, `image=zed378/aidss-trader:9ae191a`; `anchor.jsonl` is still append-only (`chattr +a`, 5 lines), no container left behind. `/etc/cron.d/aidss-anchor` was not touched.

Also observed while checking: the cron has run every hour with `rc=0` since 2026-11-18 (the long-pending "first scheduled run" is answered). The head hash stayed at seq 39 overnight because no audit entry was written in that time; that is a quiet system, not a stopped anchor.
Not done: deleting `aidss-trader:7d03693` from the registry (waits for the owner's word); installing the anchor freshness watcher (needs the threshold and channel decisions).
Rollback: `sudo cp -p /usr/local/bin/aidss-anchor.bak-20261119 /usr/local/bin/aidss-anchor` (the old file pins `7d03693`, so that image must still exist locally or in the registry).
