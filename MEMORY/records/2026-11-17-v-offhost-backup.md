# V - Encrypted off-host backup preparation

**Date:** 2026-11-17
**Task:** Stage 11 V
**Author:** Roo, second agent
**Spec refs:** stage-11 prompt; operations backup policy and R9; ADR-040

## Hook

The encrypted copy is prepared locally; no real backup has left the host. A successful fixture check is not a production restore rehearsal.

## What Changed

Completed the pre-existing backup script and tests. The script streams a fixed remote dump pipeline through SSH into OpenSSL AES-256-CBC with PBKDF2/600000 iterations, uses pipe FDs for the passphrase, atomically claims output names, and cleans owned partial files on failure/signals. It verifies gzip integrity, roles, COPY termination and the cluster footer without materializing plaintext. R9 documents owner use, checksum limitations and isolated restore rehearsal.

## Why and Alternatives

The owner selected manual encrypted copies to their computer. Plaintext staging and passphrase arguments/environment/files are excluded by the prompt. Bash process substitution uses builtin printf and pipe FDs; no external printf receives the passphrase. The checksum is unkeyed and AES-CBC is not authenticated encryption; this is documented rather than represented as tamper protection.

## What Surprised Me

Python Windows text input changes LF to CRLF, altering the test passphrase. Calling MSYS OpenSSL directly from Python also hung. Tests now send bytes and invoke OpenSSL via Git Bash, with timeouts.

## Tests

Local fixture tests: roundtrip/checksum/no leak, wrong passphrase, overwrite refusal, incomplete/truncated dump cleanup, failed source pipeline, broken gzip, empty dump, footer inside COPY, empty passphrase and LF checks. Combined V/W run: `13 passed in 44.48s`. Full-suite evidence is in the stage-11 handoff. Windows mode assertions are skipped by platform; Bash syntax and output ownership are checked locally. No host, vendor or exchange call was made.

## Definition of Done

Mechanism, tests, R9 and backup policy are written. Local-only evidence is distinguished from owner execution. Required lint/full-suite outcomes are recorded in the handoff. Trading code, architecture guard and deployment files were not changed.

## Security and What to Watch

Only encrypted artifacts and a checksum are written. Passphrase custody and Windows destination ACLs remain the owner's responsibility. Keep the master key separate. Remote Bash must be available. Multi-database dump snapshots are not globally atomic; freeze writers for migration fingerprint comparisons.

## What Was Not Determined

Real SSH failure behavior, real data restore, Unix permissions on a native Unix filesystem, Windows ACL correctness, retention/frequency, real off-host copy and recovery timing. Nothing is deployed.

## Follow-Ups

Owner runs a real copy and isolated restore, chooses retention/frequency under ADR-040, and records measured recovery evidence. See stage-11 handoff and TASKS/BACKLOG.md.
