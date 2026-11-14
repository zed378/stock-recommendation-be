"""Redaction for audit `before`/`after` payloads.

Interim: a deny-pattern on key names. docs/09-SECURITY-PRIVACY/05 prefers an
allowlist (a new sensitive field added upstream is then dropped by default);
that arrives with the first payloads that have a fixed shape. Until then a
caller must still never put a secret in a payload, and this is the second line,
not the first.
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE = re.compile(
    r"(key|secret|token|password|passwd|signature|authorization|uid|balance|ciphertext)",
    re.IGNORECASE,
)
REDACTED = "***"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SENSITIVE.search(str(k)) else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
