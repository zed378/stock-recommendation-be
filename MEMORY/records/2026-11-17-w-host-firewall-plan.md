# W - Host firewall proposal, unapplied

**Date:** 2026-11-17
**Task:** Stage 11 W
**Author:** Roo, second agent
**Spec refs:** stage-11 prompt and the 2026-11-17 host port inventory

## Hook

The owner's workstation is outside the VM subnet. Assuming the VM subnet as the SSH allowlist would lock out the owner.

## What Changed

Added operations document 08, the dedicated inet table draft and a disabled apply-with-rollback shell draft. The port table includes every inventoried service and asks for A/B/C/D choices for unrelated projects. The design scopes original destination ports after DNAT and uses IPv4/IPv6 sets. Every source is an empty placeholder. The wrapper exits 2 before action; its comments specify the future timer/rollback procedure.

## Why and Alternatives

Direct nftables is proposed for a single visible family-parity policy. ufw alone misses Docker forwarding. ufw plus iptables/ip6tables DOCKER-USER is possible but creates multiple policy owners. This is a proposal, not an accepted deployment architecture or permission to apply.

## Tests

Four local tests cover LF/draft labels, shell syntax, disabled execution with mutating commands stubbed, and original-port/both-family structure. Combined V/W result: `13 passed in 44.48s`. nft is unavailable locally: nft syntax NOT VALIDATED. No rule, timer or host file was changed. Real SSH, project access, IPv6 and persistence are not tested.

## Definition of Done

The requested plan and drafts are written and local shell/stub checks pass. Host application remains outside this task. The catalog and progress board point to this plan. Full lint/suite evidence is in the handoff.

## Security and What to Watch

Never load the draft: empty SSH sources deny new non-netbird sessions. Do not flush Docker/netbird tables. A future approved renderer must preserve per-port policy differences, original-port matching and IPv6 parity. Retain a second SSH session and console recovery; arm and verify rollback before loading.

## What Was Not Determined

Java 6547 identity, actual service clients/subnets, netbird ACLs, Docker backend and IPv6 behavior, UDP consumers, inter-project dependencies, persistence tooling, policy application or rollback timing. See document 08 unknowns.

## Follow-Ups

Owner answers each port question, then a separate host change renders and validates a policy, rehearses timer rollback on a clone, checks each source family/project and persists only after reboot tests. TASKS/BACKLOG.md tracks this. No ADR is marked accepted for this unapplied proposal.
