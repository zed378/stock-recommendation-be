# Host `10.1.200.13`: listening ports and firewall state (2026-11-17, read-only inventory)

Taken over SSH as `infra` with `sudo -n` for `ss -p`, `ufw status`, `iptables -S` and `nft list tables`. Nothing was changed. No secret is in this file. Purpose: the input for a firewall plan (not written yet, not applied).

## Host

Ubuntu 26.04.1 LTS, kernel 7.0.0-38. Interfaces: `enp1s0` 10.1.200.13/24 (the LAN address of the AIDSS VM), `enp2s0` 10.10.10.70/24, `lo`, many Docker bridges (`br-*`), and `wt0` (netbird, the DNS listener `100.81.48.163:53` is netbird).
`ufw`: **inactive**. `iptables`: `INPUT` policy `ACCEPT`, one rule `-A INPUT -i wt0 -j ACCEPT`; `DOCKER-USER` chain exists and is empty; nftables tables: `ip/ip6 nat`, `ip/ip6 filter`, `ip raw`, `ip netbird`.
`sshd`: port 22 on `0.0.0.0` and `[::]`, **`PermitRootLogin yes`, `PasswordAuthentication yes`**, `PubkeyAuthentication yes`, no `AllowUsers`. Current SSH sessions come from the owner's workstation (`10.1.101.50`).

## Listening on every interface (`0.0.0.0` / `[::]`)

| Port | Process | Owner project (by container name) |
|---|---|---|
| 22 | sshd | host |
| 6547 | java | not identified (a host process, not a container) |
| 8000, 9443 | docker-proxy | `portainer` (Portainer, the Docker management UI) |
| 8080 | docker-proxy | `stirling-pdf` |
| 8880 | docker-proxy | `bentopdf` |
| 8200, 8300 | docker-proxy | `libreoffice` |
| 9000, 9001 | docker-proxy | `hexstrike-pentest`, `hexstrike-codescan` (security tooling) |
| 17080, 17081 | docker-proxy | `central-dashboard-nginx`, `central-dashboard-nginx-preview` |
| 18000, 18100, 18200, 18300 | docker-proxy | `wedding-staging-api`, `-web-app`, `-public-invite`, `-admin` |
| 19080 | docker-proxy | `callibrator-nginx-1` |

## Loopback only (`127.0.0.1`)

`5173` (`stocks-frontend-1`, AIDSS, bound 2026-11-17), `20241` (cloudflared metrics), `6010` (sshd X11 forwarding), `10800 10920 10925 10930 10940 10941` (`zedauth-*`), `17432` (central-dashboard-postgres), `19000 19432 19673` (callibrator backend, postgres, rabbitmq UI), `53` (systemd-resolved). AIDSS publishes nothing else: PostgreSQL 5432, the api 7153 and the Trader 8001 are not published.

## Facts that shape any firewall plan

- **Docker-published ports bypass `ufw`.** Docker inserts its own `nat`/`FORWARD` rules, so `ufw allow/deny` on a published port has no effect; filtering them needs rules in the `DOCKER-USER` chain (empty today). A plan that only enables `ufw` would leave every container port above reachable.
- The host serves several unrelated projects. A rule written for AIDSS can break another project's users; the owner of each (or the owner) has to confirm what each port is for before it is closed.
- The public AIDSS site does not use any listening port from outside: it enters through the host `cloudflared`, which reaches `127.0.0.1:5173`.
- `portainer` (9443, 8000) and `hexstrike-*` (9000, 9001) are administrative and security tools reachable from the whole LAN today.
- SSH with password authentication and root login is enabled; the AIDSS deploy itself uses the password for `infra` (`HOST_PW`), so changing it affects the deploy procedure.
- The owner's workstation is `10.1.101.50` (a different subnet from the VM's `10.1.200.0/24`), so a LAN-source allow rule must name it or its subnet; a wrong source rule locks the owner out.
