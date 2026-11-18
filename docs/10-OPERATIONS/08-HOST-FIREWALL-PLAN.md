# 08 - Host firewall plan

**DRAFT, NOT APPLIED.** The owner requested a plan on 2026-11-17. This is a proposal for review, not authorization to change the host. The sole source of host facts is [the port inventory](../../MEMORY/records/2026-11-17-host-port-inventory.md). No host was contacted while writing this plan.

## Approach

Choose direct nftables in a dedicated `inet aidss_host_draft` table, with input and forward hooks before the normal filter priority. Docker-published ports pass through DNAT and forwarding, bypassing a host-input-only ufw policy. This forward hook is the equivalent of DOCKER-USER filtering; the existing empty DOCKER-USER chain and Docker-owned tables remain untouched. The inventory shows both IPv4 and IPv6 filter tables, but the active Docker backend/version must still be checked before application.

An alternative is ufw for host INPUT plus iptables/ip6tables DOCKER-USER rules for containers. That introduces two policy owners and separate IPv6 maintenance. A single inet table makes family parity visible, but requires the operator to manage persistence and Docker/netbird interaction explicitly. Do not enable ufw alongside this proposal without reviewing combined verdicts.

The draft in `deploy/host/firewall/docker-user.nft` has empty source sets. Comments are placeholders to fill from the owner's answers, not invented networks. It must not be loaded as written: its SSH restriction would deny new non-netbird SSH sessions. Managed container ports are also empty until approved. Rules preserve loopback, established/related connections and the existing wt0 allowance. Forward filtering scopes incoming external interfaces only, then matches connection-tracking original destination ports after DNAT. Each managed port would allow approved LAN sources and wt0, and drop other sources in both families. Other ports and bridge traffic retain their existing policy. A close or wt0-only answer requires rendering a separate per-port rule without the LAN allowance; never put incompatible policies into the same managed set.

The input policy remains accept for unreviewed services; this is scoped hardening, not a complete default-deny firewall. Java 6547 requires a separately reviewed INPUT rule after identification. Unknown UDP listeners, forwarding and egress are not restricted here. ICMP and IPv6 neighbor discovery remain unaffected.

## Owner decisions per port

For each question, record an answer before rendering rules: **A** leave reachable as today; **B** restrict to explicitly named LAN sources plus wt0; **C** wt0/netbird only; **D** close remote access. B requires exact CIDRs for both families, or an explicit decision to deny remote IPv6. Do not assume the VM's subnet covers the owner's computer.

| Port(s) | Inventory owner | Proposal/question | Owner confirmation needed |
|---|---|---|---|
| 22 | Host sshd | Keep `10.1.101.50/32` and wt0, or an explicitly supplied workstation subnet plus wt0? Supply IPv6 sources or deny new remote IPv6 SSH. | Yes, exact sources and working second session |
| 6547 | Host java, unidentified | Identify the process and users first; choose A/B/C/D after identification? | Yes |
| 8000, 9443 | portainer | Administrative surface: B, C, D, or A for a known dependency? | Yes, both ports |
| 8080 | stirling-pdf | A/B/C/D for existing users? | Yes |
| 8880 | bentopdf | A/B/C/D for existing users? | Yes |
| 8200, 8300 | libreoffice | A/B/C/D; do these ports serve integration clients? | Yes, each port |
| 9000, 9001 | hexstrike-pentest / hexstrike-codescan | B/C/D, or A for a documented integration? | Yes, each project |
| 17080, 17081 | central-dashboard-nginx / preview | A/B/C/D for main and preview separately? | Yes |
| 18000, 18100, 18200, 18300 | wedding-staging-api / web-app / public-invite / admin | A/B/C/D separately; which need a tunnel or LAN integration? | Yes, each service |
| 19080 | callibrator-nginx-1 | A/B/C/D for existing users? | Yes |
| 5173 | AIDSS frontend, loopback only | Leave `127.0.0.1` binding unchanged; host cloudflared uses it. | No new publication authorized |
| 5432, 7153, 8001 | AIDSS PostgreSQL / API / Trader, unpublished | Preserve unpublished state. No firewall rule may publish or widen access. | No new publication authorized |
| 20241 | cloudflared metrics, loopback | Preserve loopback binding. | Confirm before any later change |
| 6010 | sshd X11 forwarding, loopback | Preserve loopback binding. | Confirm before any later change |
| 10800, 10920, 10925, 10930, 10940, 10941 | zedauth, loopback | Preserve loopback bindings. | Confirm before any later change |
| 17432 | central-dashboard PostgreSQL, loopback | Preserve loopback binding. | Confirm before any later change |
| 19000, 19432, 19673 | callibrator backend / PostgreSQL / RabbitMQ UI, loopback | Preserve loopback bindings. | Confirm before any later change |
| 53 | systemd-resolved loopback; netbird at `100.81.48.163` | Preserve observed DNS access; confirm clients/protocols before restrictions. | Yes for any future restriction |

No unrelated project is approved for closure. Existing public AIDSS access is outbound cloudflared to loopback and must continue to work.

## Owner decisions recorded (2026-11-17, stage 1)

| Question | Answer |
|---|---|
| SSH (22) sources | `10.1.101.0/24` plus netbird (`wt0`) |
| Portainer (8000, 9443) sources | `10.1.101.0/24` plus netbird (`wt0`) |
| IPv6 | Deny new remote IPv6 for these ports |
| Other projects (6547, 8080, 8880, 8200, 8300, 9000, 9001, 17080, 17081, 18000 to 18300, 19080) | Untouched in stage 1; client inventory first |

Netbird: the owner asked for netbird access from other devices. Netbird peers arrive on interface `wt0`, which the draft already admits for SSH and for every published port, so no netbird address range is listed. A CIDR such as `100.64.0.0/10` would be weaker (a LAN host could spoof a `100.x` source), and the real netbird range was not read from the host. The owner administers netbird and reports full access to the subnets (2026-11-17, stated, not checked from the host), so no ACL change is expected; the second-session test over netbird still proves it.

Consequences to accept before applying: other hosts on `10.1.200.0/24` and `10.10.10.0/24` lose SSH and Portainer; the owner's own device must be inside `10.1.101.0/24` or on netbird. The draft values are in `deploy/host/firewall/docker-user.nft`; they are unvalidated by `nft -c` and not applied.

## Lockout prevention and rollback

`deploy/host/firewall/apply-with-rollback.sh` is deliberately disabled (exit 2 before any action). Its comments specify the review/application sequence. Only syntax checking and tests with command stubs are permitted at this stage.

Before any future application, obtain console access, retain the original SSH session, and open a second session from the owner's workstation. Confirm the source observed by sshd; `10.1.101.50` is on a different subnet from `10.1.200.0/24`. Never infer a workstation subnet mask from this inventory. Check wt0/netbird SSH separately.

Use a private saved ruleset as evidence, but rollback must delete **only** the newly owned inet table, not flush/restore the entire ruleset over Docker or netbird changes. Refuse an existing same-name table. A root-owned rollback script uses an absolute nft path and handles an already absent table. Arm `systemd-run --unit=aidss-firewall-rollback --on-active=5m /absolute/reviewed-rollback-script` and verify the timer is active before loading the reviewed policy. Five minutes is a proposed operational test window, not a trading limit. On load or verification failure run rollback immediately; otherwise let the timer restore access. Only after the following checks pass may the owner cancel the timer:

1. A new second SSH session from every approved source (IPv4, approved IPv6, wt0).
2. Public AIDSS login and health still answer; unauthorized Trader status remains 401.
3. Each confirmed project works from allowed clients and refuses excluded clients, including IPv6.
4. Cross-project integrations and Docker bridge traffic continue to work; AIDSS ports remain unpublished/loopback.

Rollback execution and elapsed time have not been measured. Keeping an established session is not proof that a new SSH connection is allowed.

## Persistence

After owner approval and rehearsal on a clone, install a root-owned dedicated systemd oneshot policy loader, ordered after network, Docker and netbird, with explicit failure handling and reload behavior. Keep its configuration separate from Docker-generated nftables rules. Do not place a global `flush ruleset` into `/etc/nftables.conf`. Test Docker restart, netbird restart and reboot on a clone before enabling persistence on the host. An existing table must be replaced transactionally by reviewed tooling, not accumulated with repeated adds. Persistence is designed here but no unit is installed or claimed tested. A later backend change requires a new check of hook order and IPv6 paths.

## Separate optional SSH hardening

The inventory reports `PasswordAuthentication yes` and `PermitRootLogin yes`. Changing these is separate from firewall work. If the owner chooses key-only SSH, install and test an infra public key in a new session first, retain console recovery, validate with `sshd -t`, then reload and test again before ending existing sessions. Update the deploy procedure because its current HOST_PW password method will stop working. Root login can be disabled independently after testing infra sudo access. Options for the owner: keep current authentication temporarily; disable root login first; or migrate infra deployment to keys and then disable password/root login. No SSH settings are changed by this plan.

## Read-only verification for the main agent

Run on the host only with owner authorization, and retain outputs without secrets:

```sh
sudo nft list ruleset
sudo iptables -S DOCKER-USER
sudo ip6tables -S DOCKER-USER
sudo ss -ltnp
ip -brief address
docker ps --format '{{.Names}} {{.Ports}}'
```

From the owner's computer, check approved service URLs with curl, the public AIDSS login/health and connection refusal for 5432/7153/5173 on the LAN address. Inventory those URLs before testing; do not invent endpoints for other projects. Inspect the backend and nft version before `nft -c -f` on a rendered policy. This draft has not been validated by nft unless the accompanying record explicitly supplies a successful local check.

Planning is complete when every proposal and unknown is recorded and drafts have syntax evidence. Application is complete only after owner choices, rendered-policy review, timed rollback rehearsal, second-session tests, project checks, IPv6 checks and persistence rehearsal are recorded. No live hardening completion is claimed here.

## Stage 2 inventory

Before drafting Stage 2 restrictions for non-AIDSS services (including `java` on `6547`), run `deploy/host/firewall/inventory-clients.sh` on the host (read-only, requires `python3`, `ss`, `docker`, `ps`, `systemctl`):

```sh
sudo sh deploy/host/firewall/inventory-clients.sh [PORT ...]
```

It reports listening processes (`ss -H -ltnp`), published container port mappings (`docker ps` with `com.docker.compose.project`), established client counts grouped by source IP and IPv4 `/24` (IPv4 and IPv6 separated), and for `6547` prints only the executable name, PID, user, `/proc/<pid>/cwd`, and systemd unit (never `cmdline` or `environ`, and never packet/application data). Because established connections are point-in-time snapshots (zero clients now does not prove a port is unused), repeat the capture at several different hours and retain the outputs privately for Stage 2 owner decisions.

## Unknowns

Identity and clients of java 6547; other LAN users and their subnet masks; netbird ACLs and IPv6 address allocation; external interface routing; IPv6 Docker publication behavior/backend; UDP consumers; bridge integrations; existing persistence tooling; tunnel paths of other projects; and whether each project can tolerate restrictions. These block a final restrictive policy, not writing this plan.
