# Firewall stage 1: owner answers rendered into the draft

Date: 2026-11-17. Documentation and draft only; no host contact, nothing applied, nft not run.

Owner answers (multiple choice, then typed): SSH and Portainer sources `10.1.101.0/24` plus netbird; deny new remote IPv6; other projects untouched in stage 1.

Changes: `docker-user.nft` now carries `10.1.101.0/24` in `ssh_v4` and `lan_v4`, ports 8000 and 9443 in `managed_tcp`, IPv6 sets empty; document 08 records the answers and consequences; the test asserts the exact values.

Netbird: admitted by interface `wt0` (already in the draft), not by a CIDR. A `100.x` range would be spoofable from the LAN and the real range was not read from the host.

Still needed before application: `nft -c -f` on a rendered file, timed rollback rehearsal, second SSH session from `10.1.101.0/24` and from netbird, and the client inventory for the other projects. Hosts on `10.1.200.0/24` and `10.10.10.0/24` would lose SSH and Portainer.
