"""
Load a filled owner-numbers profile into a running Trader, through the Trader's own API.

    python deploy/trader/import_owner_profile.py PROFILE.json --email you@example.com
    python deploy/trader/import_owner_profile.py PROFILE.json --email you@example.com --apply

The first line is a dry run; the second writes. What it does, and what it deliberately does not:

* It signs in as **you**, with your password typed at a prompt (never an argument, never an
  environment variable, never written anywhere), and calls the same `/trader/v1` routes the
  screens call. So every rule the screens meet applies here too: permissions, range checks, the
  step-up for anything that loosens a limit, audit entries, and the rule that a changed strategy
  version starts again in PAPER.
* The default is a **dry run**: it checks the file (`check_owner_defaults.py`), reads what the
  Trader holds now, and prints current against proposed for every field. It changes nothing.
* `--apply` writes only when the file says `"status": "accepted"`. The starter profiles say
  `proposed`; changing that word is the owner's act, and this tool treats it as the decision. It
  then asks you to type APPLY after showing the differences.
* It never resumes trading, never changes a mode, never promotes a strategy, never touches
  credentials, and never calls an exchange. The instance stays `HALTED`, every strategy `PAPER`.
* A step-up grant is minted from your password for each write that loosens something, used once.

Stdlib only; the checker needs the repository's own package, so run it from the repository's
environment.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "https://aidss.zedth.my.id"
STRATEGY = "ema_adx"
INT_LIMITS = {
    "max_consecutive_losses",
    "max_open_positions",
    "freshness_limit_s",
    "cooldown_s",
    "order_rate_limit",
}

# The sections, in the order they are written. Strategy parameters and the paper
# model first, because they cannot loosen anything; the three that can, afterwards.
SECTIONS = ("strategy_params", "paper", "limits", "allowlist", "promotion_thresholds")

Send = Callable[[str, str, dict[str, str], Any], tuple[int, Any]]


class ImportError_(Exception):
    """Something went wrong in a way the person running this needs to read."""


# ----------------------------------------------------------------------------- transport


def http_send(method: str, url: str, headers: dict[str, str], body: Any) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, None
    except urllib.error.URLError as exc:
        raise ImportError_(f"cannot reach {url}: {exc.reason}") from None


def _reason(status: int, payload: Any) -> str:
    """The server's own words for a refusal, and nothing else from the response."""
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        if isinstance(err, dict) and err.get("message"):
            return f"{status} {err.get('code', '')}: {err['message']}".strip()
        if payload.get("detail"):
            return f"{status}: {payload['detail']}"
    return f"{status}"


class Client:
    def __init__(self, base: str, send: Send = http_send) -> None:
        self.base = base.rstrip("/")
        self._send = send
        self._token: str | None = None
        self._email: str | None = None
        self._password: str | None = None

    def login(self, email: str, password: str) -> None:
        status, payload = self._send(
            "POST",
            f"{self.base}/api/auth/login",
            {"Content-Type": "application/json"},
            {"email": email, "password": password},
        )
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise ImportError_(f"sign-in refused ({_reason(status, payload)})")
        self._token, self._email, self._password = payload["access_token"], email, password

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"}
        headers.update(extra or {})
        return headers

    def get(self, path: str) -> Any:
        status, payload = self._send("GET", f"{self.base}/trader/v1{path}", self._headers(), None)
        if status != 200:
            raise ImportError_(f"GET {path} refused ({_reason(status, payload)})")
        return payload["data"]

    def grant(self) -> str:
        """A single-use step-up grant, valid for five minutes, for loosening something."""
        status, payload = self._send(
            "POST",
            f"{self.base}/trader/v1/stepup",
            self._headers({"Idempotency-Key": str(uuid.uuid4())}),
            {"email": self._email, "password": self._password, "scope": "RAISE_LIMIT"},
        )
        if status != 200:
            raise ImportError_(f"step-up refused ({_reason(status, payload)})")
        return payload["data"]["grant"]

    def put(self, path: str, body: Any) -> Any:
        """PUT; if the server asks for a step-up grant, mint one and send the write once more."""
        for attempt in (1, 2):
            extra = {"Idempotency-Key": str(uuid.uuid4())}
            if attempt == 2:
                extra["X-Step-Up"] = self.grant()
            status, payload = self._send(
                "PUT", f"{self.base}/trader/v1{path}", self._headers(extra), body
            )
            code = (
                ((payload or {}).get("error") or {}).get("code")
                if isinstance(payload, dict)
                else None
            )
            if status == 403 and code == "step_up_required" and attempt == 1:
                continue
            if status != 200:
                raise ImportError_(f"PUT {path} refused ({_reason(status, payload)})")
            return payload["data"]
        raise ImportError_(f"PUT {path} still needs a step-up after one was supplied")


# ----------------------------------------------------------------------------- the profile


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_owner_defaults", HERE / "check_owner_defaults.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def requests_for(profile: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    """Section name to (PUT path, body), the shapes the Trader's routes accept."""
    limits = {
        k: (v if v is None or k == "trading_window" else (int(v) if k in INT_LIMITS else str(v)))
        for k, v in profile["limits"].items()
    }
    al = profile["allowlist"]
    th = profile["promotion_thresholds"]
    return {
        "strategy_params": (
            f"/strategies/{STRATEGY}/parameters",
            {
                k: (v if isinstance(v, int) else str(v))
                for k, v in profile["strategy_params"].items()
            },
        ),
        "paper": ("/paper-config", {k: str(v) for k, v in profile["paper"].items()}),
        "limits": ("/limits", {"limits": limits}),
        "allowlist": (
            "/allowlist",
            {
                "pairs": list(al["pairs"]),
                "min_quote_volume_24h_idr": str(al["min_quote_volume_24h_idr"]),
                "max_spread_pct": str(al["max_spread_pct"]),
            },
        ),
        "promotion_thresholds": (
            "/promotion-thresholds",
            {k: (v if isinstance(v, int) else str(v)) for k, v in th.items()},
        ),
    }


def current_state(client: Client) -> dict[str, dict[str, Any]]:
    """What the Trader holds now, flattened to the same keys the profile uses."""
    out: dict[str, dict[str, Any]] = {}
    params = client.get(f"/strategies/{STRATEGY}/parameters")
    out["strategy_params"] = dict(params.get("params") or {})
    paper = client.get("/paper-config")
    out["paper"] = {k: paper.get(k) for k in paper if k not in ("configured", "paper_fills")}
    out["limits"] = dict(client.get("/limits").get("limits") or {})
    allow = client.get("/allowlist")
    out["allowlist"] = {
        k: allow.get(k) for k in ("pairs", "min_quote_volume_24h_idr", "max_spread_pct")
    }
    out["promotion_thresholds"] = dict(client.get("/promotion-thresholds").get("thresholds") or {})
    return out


def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, list | tuple) or isinstance(b, list | tuple):
        return [str(x) for x in a] == [str(x) for x in b]
    try:
        from decimal import Decimal

        return Decimal(str(a)) == Decimal(str(b))
    except Exception:  # noqa: BLE001 - not numbers: compare as text
        return str(a) == str(b)


def differences(
    now: dict[str, dict[str, Any]], wanted: dict[str, tuple[str, Any]]
) -> list[tuple[str, str, Any, Any]]:
    rows: list[tuple[str, str, Any, Any]] = []
    for section in SECTIONS:
        body = wanted[section][1]
        flat = body["limits"] if section == "limits" else body
        for key, value in flat.items():
            have = now[section].get(key)
            if not _same(have, value):
                rows.append((section, key, have, value))
    return rows


def show(rows: list[tuple[str, str, Any, Any]], out: Callable[[str], None] = print) -> None:
    if not rows:
        out("The Trader already holds every value in this file.")
        return
    width = max(len(f"{s}.{k}") for s, k, _, _ in rows)
    for section, key, have, value in rows:
        out(
            f"  {f'{section}.{key}':<{width}}  {'(unset)' if have is None else str(have):>14}"
            f"  ->  {value}"
        )


# ----------------------------------------------------------------------------- the run


def run(
    profile: dict[str, Any],
    client: Client,
    *,
    apply: bool,
    confirm: Callable[[], str] = lambda: input("Type APPLY to write these values: "),
    out: Callable[[str], None] = print,
) -> int:
    checker = load_checker()
    problems = checker.problems(profile)
    for line in problems:
        out(f"PROBLEM: {line}")
    if problems:
        out("Fix the file first; nothing was read from or written to the Trader.")
        return 2

    wanted = requests_for(profile)
    rows = differences(current_state(client), wanted)
    equity = profile.get("basis", {}).get("equity_idr", "?")
    out(f"Profile: {equity} IDR, status {profile.get('status')!r}")
    show(rows, out)

    if not apply:
        out("Dry run: nothing was written. Add --apply to write.")
        out('(The file must say "status": "accepted" for that.)')
        return 0
    if profile.get("status") != "accepted":
        out(f'Not applied: the file says "status": "{profile.get("status")}".')
        out('Change it to "accepted" yourself once you have decided.')
        return 3
    if not rows:
        return 0
    if confirm().strip() != "APPLY":
        out("Not applied.")
        return 4

    for section in SECTIONS:
        path, body = wanted[section]
        result = client.put(path, body)
        extra = ""
        if section == "limits":
            extra = (
                f" (version {result.get('version')}, still unset: {result.get('unset') or 'none'})"
            )
        elif section == "allowlist":
            extra = f" (active: {result.get('active')})"
        elif section == "strategy_params":
            extra = f" (version {result.get('version')}, mode {result.get('mode')})"
        out(f"written: {section}{extra}")

    left = differences(current_state(client), wanted)
    if left:
        out("Differences that remain after writing (the Trader normalised or refused them):")
        show(left, out)
        return 5
    out("Verified: the Trader now holds every value in the file.")
    out("Trading state and strategy modes were not touched.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("profile", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv[1:])
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    password = getpass.getpass(f"Password for {args.email}: ")
    client = Client(args.base_url)
    try:
        client.login(args.email, password)
        return run(profile, client, apply=args.apply)
    except ImportError_ as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        del password


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
