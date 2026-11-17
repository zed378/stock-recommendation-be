#!/bin/sh
# DRAFT, NOT APPLIED. Syntax checking is permitted; execution is deliberately blocked.
# Owner approval must produce a reviewed, rendered policy and a separate application change.
set -eu
printf '%s\n' 'DRAFT ONLY: no firewall rule, timer, or host file was changed.' >&2
exit 2

# Reviewed application procedure for the main agent/owner, not executable draft code:
# 1. Keep an SSH session open and obtain console access. Check nft and Docker backends.
# 2. Save the existing rules privately; do not flush any Docker or netbird tables.
# 3. Render only an owner-approved policy into a root-owned, non-writable file.
# 4. Run nft -c -f on that file. Refuse if aidss_host_draft already exists.
# 5. Prepare a root-owned rollback script that deletes ONLY inet aidss_host_draft.
#    It must use a fixed absolute nft executable path and succeed if the table is absent.
# 6. Arm systemd-run --unit=aidss-firewall-rollback --on-active=5m
#    with the absolute rollback-script path. Confirm the timer is active BEFORE loading.
# 7. Load with nft -f. Any failure triggers the same rollback immediately.
# 8. Open a SECOND SSH session from every approved source, check the public AIDSS site
#    and each approved project from allowed and denied sources, including IPv6.
# 9. Only after all checks, cancel aidss-firewall-rollback.timer. Keep rollback available.
# 10. Enable the dedicated persistent unit only after reboot/restart tests on a clone.
