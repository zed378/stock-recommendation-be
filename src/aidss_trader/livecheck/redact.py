"""Redaction and shape description for the live verification (docs/06-INTEGRATIONS/14).

Two different jobs, kept apart on purpose:

* `describe_shape` keeps only structure: key names and value types. It is what a signed
  (account-specific) response is reduced to, so no balance, order, or id ever reaches a stored file.
* `redact_public` keeps the values of a public response (prices are not secrets) but truncates long
  lists, and still strips any field that could identify an account.

`scrub` removes known secret strings from any text, as a last line of defence for a message that
might echo a request.
"""

from __future__ import annotations

import re
from typing import Any

# Field names that are removed wherever they appear, in any response.
_ALWAYS_REMOVE = {"uid", "sign", "signature", "apikey", "x-apikey", "api_key", "secret", "key"}
_NUMERIC = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")
MAX_ITEMS = 3


def describe_shape(value: Any, _depth: int = 0) -> Any:
    """Structure without values. Numeric strings are marked, because string-versus-number typing
    is one of the things the check exists to observe (D12)."""
    if _depth > 6:
        return "..."
    if isinstance(value, dict):
        return {
            k: describe_shape(v, _depth + 1)
            for k, v in value.items()
            if k.lower() not in _ALWAYS_REMOVE
        }
    if isinstance(value, list):
        return ["list", len(value), describe_shape(value[0], _depth + 1) if value else None]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "numeric-string" if _NUMERIC.fullmatch(value.strip()) else "string"
    return type(value).__name__


def redact_public(value: Any, _depth: int = 0) -> Any:
    """A public response with its values, long lists cut to a few items, identifiers removed."""
    if _depth > 6:
        return "..."
    if isinstance(value, dict):
        return {
            k: redact_public(v, _depth + 1)
            for k, v in value.items()
            if k.lower() not in _ALWAYS_REMOVE
        }
    if isinstance(value, list):
        head = [redact_public(v, _depth + 1) for v in value[:MAX_ITEMS]]
        return head if len(value) <= MAX_ITEMS else {"truncated_list_of": len(value), "first": head}
    return value


def scrub(text: str, secrets: list[str]) -> str:
    """Remove any known secret from a string, whatever surrounds it."""
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "<removed>")
    return text
