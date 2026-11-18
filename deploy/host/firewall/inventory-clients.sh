#!/bin/sh
# Python's ipaddress parser keeps IPv6 and IPv4 grouping separate without shell eval.
set -eu
exec python3 - "$@" <<'PY'
import collections
import ipaddress
import json
import os
import pathlib
import re
import subprocess
import sys

# All ports are from document 08's inventory table, including loopback/unpublished entries.
DEFAULT = '22 6547 8000 9443 8080 8880 8200 8300 9000 9001 17080 17081 18000 18100 18200 18300 19080 5173 5432 7153 8001 20241 6010 10800 10920 10925 10930 10940 10941 17432 19000 19432 19673 53'
if sys.argv[1:] == ['--help']:
    print('Usage: inventory-clients.sh [PORT ...]; requires python3, ss, docker, ps, systemctl.')
    print('Point-in-time clients only: repeat at different hours and retain results privately.')
    print('Zero clients now does not mean unused. No packet, cmdline or environ contents printed.')
    sys.exit(0)
try:
    ports = {int(p) for p in (sys.argv[1:] or DEFAULT.split())}
    if not ports or any(p < 1 or p > 65535 for p in ports):
        raise ValueError
except ValueError:
    print('Invalid port list', file=sys.stderr)
    sys.exit(3)

failed = False

def run(args):
    global failed
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        failed = True
        print('UNAVAILABLE: ' + args[0], file=sys.stderr)
        return ''

def endpoint(value):
    address, port = value.rsplit(':', 1)
    return address.strip('[]'), int(port)

print('Point-in-time only; repeat at different hours. No application data is collected.')
print('PORTS', *sorted(ports))
listeners = run(['ss', '-H', '-ltnp'])
java_pids = set()
for line in listeners.splitlines():
    fields = line.split()
    try:
        address, port = endpoint(fields[3])
    except (ValueError, IndexError):
        continue
    if port in ports:
        # ss exposes comm/PID/fd here, never process argv.
        print('LISTENER', json.dumps(line))
    if port == 6547 and 6547 in ports:
        java_pids.update(re.findall(r'pid=(\d+)', line))

for family in (4, 6):
    counts = collections.Counter()
    groups = collections.Counter()
    text = run(['ss', '-H', '-tn' + str(family), 'state', 'established'])
    for line in text.splitlines():
        fields = line.split()
        # With a state filter ss omits the State column: Recv-Q Send-Q Local Peer.
        try:
            _, port = endpoint(fields[2])
            source, _ = endpoint(fields[3])
            ip = ipaddress.ip_address(source.split('%', 1)[0])
        except (ValueError, IndexError):
            continue
        if port not in ports or ip.version != family:
            continue
        counts[port, str(ip)] += 1
        if family == 4:
            groups[port, str(ipaddress.ip_network(str(ip) + '/24', strict=False))] += 1
    print('CLIENTS_IPV' + str(family))
    for (port, address), count in sorted(counts.items()):
        print('SOURCE', port, address, count)
    for (port, network), count in sorted(groups.items()):
        print('SUBNET', port, network, count)

print('CONTAINERS (published-port mappings only; unpublished owners may remain unknown)')
containers = run(['docker', 'ps', '--format', '{{.Names}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}'])
for line in containers.splitlines():
    fields = line.split('\t')
    if len(fields) == 3 and any(
        int(p) in ports for p in re.findall(r':(\d+)->', fields[1])
    ):
        print('CONTAINER', json.dumps(fields))

for pid in sorted(java_pids):
    comm = run(['ps', '-p', pid, '-o', 'comm=']).strip()
    if comm != 'java':
        print('PORT6547_NONJAVA_OR_UNAVAILABLE', pid)
        continue
    user = run(['ps', '-p', pid, '-o', 'user=']).strip()
    unit = run(['systemctl', 'whoami', pid]).strip()
    proc = pathlib.Path('/proc') / pid
    details = {'pid': int(pid), 'user': user, 'unit': unit}
    for name in ('exe', 'cwd'):
        try:
            details[name] = os.readlink(proc / name)
        except OSError:
            details[name] = 'unavailable'
    for name in ('cmdline', 'environ'):
        try:
            # Read bytes only to count them; values never reach stdout/errors.
            details[name + '_length'] = len((proc / name).read_bytes())
        except OSError:
            details[name + '_length'] = 'unavailable'
    print('JAVA6547', json.dumps(details, sort_keys=True))
sys.exit(1 if failed else 0)
PY
