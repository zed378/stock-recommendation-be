# Stage 11 V/W/X handoff

Date/time: 2026-11-17 10:01 UTC. Agent: Roo, second agent. Implementation HEAD: c7bcfaf (real SHA before this handoff commit). Status: SELESAI for local preparation; owner execution pending.

## 1. Summary

V prepares an encrypted streaming cluster backup, cleanup and verification with hermetic tests and R9 restore instructions. W prepares the host firewall proposal, per-port owner questions, empty source placeholders and a disabled application draft. X synchronizes operating instructions with recorded hardening, audit anchoring and migration-kit facts. No SSH, external service, exchange, image build/push, deployment, real backup or firewall action occurred. Optional Y was not performed.

## 2. Commits and intentionally untouched files

Actual `git log --oneline origin/main..HEAD` before handoff:

```text
c7bcfaf docs(task-x): synchronize operating instructions and stage-11 records
97b5383 docs(task-w): prepare unapplied host firewall plan and guarded drafts
3fa8326 feat(task-v): prepare encrypted off-host backup with stream verification
```

V files: backup_offhost.sh, test_backup_offhost.py, backup policy, R9 and V record. W files: operations document 08, two firewall drafts, firewall tests and W record. X files: CLAUDE.md, PROGRESS.md, BACKLOG.md, catalog, changelog, memory index and X record. This handoff/index/final note are a separate documentation commit. Shared index/progress updates for V/W are consolidated in X, rather than duplicated across each commit. Work stayed on the shared main branch as directed by the handoff; no branch switch was made.

Intentionally untouched: src/, frontend/, docker-compose.yml, Dockerfile*, alembic*, tests/test_architecture_constraints.py, ADR-052, production and credentials. Existing V work from the stopped agent was reviewed and completed under the owner's explicit instruction.

## 3. Evidence and operator

All following evidence was run by **[second agent]**, locally.

V/W focused:

```text
.............                                                            [100%]
13 passed in 44.48s
```

Required full Trader/architecture/routing suite with original Windows PATH:

```text
5 failed, 548 passed, 15 deselected in 284.73s (0:04:44)
```

All five failures are test_aidss_anchor_script.py selecting C:\Windows\system32\bash.EXE (WSL failure before the stub). Repeated only those five with Git bin/usr/bin prepended to PATH, without edits:

```text
.....                                                                    [100%]
5 passed in 7.14s
```

Thus 553 selected tests passed across the full run and targeted environment-corrected rerun, not a claimed single green full run. PostgreSQL opt-in tests were deselected. Earlier focused run had 3 new-test portability failures, corrected by byte LF passphrase input and matching MSYS OpenSSL; the final V/W result above supersedes them.

Required lint and syntax/file checks:

```text
All checks passed!
deploy/trader/backup_offhost.sh:             Bourne-Again shell script, ASCII text executable
deploy/host/firewall/apply-with-rollback.sh: POSIX shell script, ASCII text executable
deploy/host/firewall/docker-user.nft:        ASCII text
```

Commands: ruff check src tests alembic alembic_trader deploy; bash -n backup_offhost.sh; sh -n apply-with-rollback.sh; file on all three; git diff --check. Staged V secret-pattern scan printed `Secret pattern scan: clean`. nft is unavailable: nft syntax NOT VALIDATED. Raw suite outputs are in the local TEMP files aidss-stage11-suite.txt and aidss-stage11-vw.txt; no real dump is in the repository.

## 4. Main-agent verification commands (at most eight)

Use Git Bash tools ahead of Windows WSL Bash in PATH. All tests use fixtures/stubs; do not execute a firewall draft on the host.

1. `git status --short` expects empty after handoff commit.
2. `git log --oneline origin/main..HEAD` expects V/W/X and handoff commits, no push.
3. `.venv/Scripts/ruff.exe check src tests alembic alembic_trader deploy` expects All checks passed.
4. `.venv/Scripts/python.exe -m pytest tests/trader tests/test_architecture_constraints.py tests/test_frontend_routing.py -q` expects 553 passing selected tests and 15 deselected with Git Bash PATH; collection changes may alter counts.
5. `bash -n deploy/trader/backup_offhost.sh` expects exit 0.
6. `sh -n deploy/host/firewall/apply-with-rollback.sh` expects exit 0.
7. `git diff ce44034 HEAD -- tests/test_architecture_constraints.py src frontend docker-compose.yml` expects empty.
8. `file deploy/trader/backup_offhost.sh deploy/host/firewall/apply-with-rollback.sh deploy/host/firewall/docker-user.nft` expects text without CRLF.

## 5. VERIFIED versus WRITTEN BUT NOT RUN

Verified: encrypted fixture roundtrip, wrong-passphrase refusal, checksum equality, no raw SQL/passphrase in artifacts/output, overwrite refusal, failed/incomplete source cleanup, invalid gzip/empty dump/COPY-footer rejection, local shell syntax, disabled firewall wrapper using stubs, lint and guard/routing tests. Unix mode checks are platform-skipped on Windows.

Written but not run: real SSH backup, interrupted real connection, real encrypted-dump restore, Windows ACL review, nft parser/kernel validation, host source/IPv6 tests, automatic rollback/persistence/reboot. No UI deliverable was changed, so visual skill delivery gates do not apply.

## 6. Findings and actions

Python Windows text input added CRLF to the test passphrase; fixed to byte input. MSYS OpenSSL direct subprocess input hung; tests now run it through Git Bash with timeouts. Existing anchor tests selected broken WSL Bash; Git Bash PATH makes all five pass without code edits. Remote pipefail prevents gzip success from hiding pg_dumpall failure. Atomic output claiming prevents overwrite races; partial files are deleted only if owned by this run. AES-CBC and an unkeyed sidecar are not authenticated encryption, documented in R9. Initial commentary suggesting builtin printf leaked through external argv was corrected before implementation claims.

## 7. Owner decisions pending

For each unrelated project in document 08: A leave current access, B named LAN sources plus wt0, C wt0 only, or D close? For SSH: workstation /32 plus wt0, an explicitly supplied subnet plus wt0, or wt0 only after console verification? Supply IPv6 sources or explicitly deny new remote IPv6. Identify java 6547 and bridge clients first. For backup: which frequency/retention and when to run a real isolated restore? ADR-052 remains deferred; other risk numbers/live gates remain owner-led.

## 8. Rollback

Repository changes can be reverted by their individual V/W/X commits after reviewing shared docs. Not exercised; no elapsed time measured or estimated. No host rollback is needed because no host changed. Future firewall rollback deletes only its dedicated table under a verified timer; neither application nor rollback timing has been tested.

## 9. Remaining risks

The host still has no applied firewall and no recorded real off-host copy. Empty draft SSH sets can lock out new sessions if someone bypasses the disabled wrapper and loads nft directly. Unknown cross-project clients and IPv6 behavior block final policy. Backup integrity checks do not prove recoverability or protect against an attacker replacing both encrypted file and checksum. Audit-anchor scheduled invocation/failure alerts are not established by this work. Trader remains recorded HALTED and unverified against the exchange.
