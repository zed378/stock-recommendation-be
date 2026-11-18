#!/bin/sh
# Independent local observer; never changes the anchor or contacts a service.
set -eu
exec python3 - <<'PY'
import datetime
import os
import pathlib
import re
import subprocess
import sys


def finish(code, message):
    if code:
        priority = 'user.crit' if code == 2 else 'user.err'
        try:
            subprocess.run(['logger', '-p', priority, '-t', 'aidss-anchor-watch', '--', message],
                           check=False, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        hook = os.environ.get('AIDSS_ANCHOR_ALERT_CMD')
        if hook:
            try:
                # The hook is one executable path, never evaluated as shell text.
                subprocess.run([hook, message], check=False, capture_output=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                print('Anchor alert hook failed', file=sys.stderr)
    print(message)
    sys.exit(code)

raw = os.environ.get('AIDSS_ANCHOR_MAX_AGE_S', '')
if not re.fullmatch(r'[0-9]+', raw) or int(raw) <= 0:
    finish(3, 'Anchor watch requires a positive AIDSS_ANCHOR_MAX_AGE_S; no default is set')
maximum = int(raw)
directory = pathlib.Path(os.environ.get('AIDSS_ANCHOR_DIR', '/var/lib/aidss-anchor'))
try:
    # JSONL is append-only and may not advance when the DB head is unchanged.
    # Successful wrapper timestamps, not JSONL mtime, establish cron freshness.
    with (directory / 'anchor.jsonl').open('rb') as anchor:
        if not anchor.read(1):
            finish(4, 'Anchor file missing, empty or unreadable')
    last = None
    success = None
    with (directory / 'anchor.log').open(encoding='utf-8') as log:
        for line in log:
            match = re.match(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) rc=(\d+)(?:\s|$)', line)
            if not match:
                continue
            stamp = datetime.datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.UTC).timestamp()
            last = int(match[2])
            if last == 0:
                success = stamp
except (OSError, UnicodeError, ValueError):
    finish(4, 'Anchor files missing, malformed or unreadable')
if last == 2:
    finish(2, 'Anchor audit chain verification failed')
try:
    now = float(os.environ.get('AIDSS_ANCHOR_NOW', datetime.datetime.now(datetime.UTC).timestamp()))
    if not __import__('math').isfinite(now):
        raise ValueError
except ValueError:
    finish(3, 'Anchor watch test clock is invalid')
if success is None or now < success or now - success >= maximum:
    finish(1, 'Anchor success is stale or unavailable')
if last != 0:
    finish(1, 'Anchor latest run failed')
finish(0, 'Anchor success is fresh')
PY
