"""The build output namespace must not collide with a client-side route.

This failed in production and was invisible in every other check. Vite's
default asset directory is `assets/`, the application has a route at
`/assets/:ticker`, and nginx's rule for immutable bundle files matched the
route first and answered `404`. Every refresh on an asset page died. The type
checker, the linter, and the whole Python suite were all green.

Nothing links the three files that have to agree - `vite.config.ts`, `App.tsx`,
and `nginx.conf` - so nothing would notice them drifting apart again. This test
is that link. It lives in the Python suite because that is the suite that runs
on every change; the alternative was standing up a second test runner to assert
one fact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
VITE_CONFIG = FRONTEND / "vite.config.ts"
APP = FRONTEND / "src" / "App.tsx"
NGINX = FRONTEND / "nginx.conf"


def read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path.name} is absent; the frontend is not present in this checkout")
    return path.read_text(encoding="utf-8")


def assets_dir() -> str:
    """Vite's build output directory, or its default when unset."""
    match = re.search(r'assetsDir:\s*"([^"]+)"', read(VITE_CONFIG))
    return match.group(1) if match else "assets"


def route_paths() -> list[str]:
    return re.findall(r'<Route\s+path="([^"]+)"', read(APP))


def test_the_routes_and_the_config_were_both_found() -> None:
    """Guards the guard: a renamed file would make every check below vacuous."""
    assert route_paths(), "no routes found - the regex or the file has moved"
    assert assets_dir()


def test_no_client_route_shares_a_prefix_with_the_build_output() -> None:
    """The exact failure: `/assets/:ticker` and Vite's `assets/` overlapped, so
    nginx's immutable-file rule caught the route and 404'd it."""
    directory = assets_dir()
    offenders = [
        path for path in route_paths() if path.strip("/").split("/")[0] == directory
    ]
    assert not offenders, (
        f"routes {offenders} collide with the build output directory {directory!r}. "
        "nginx will match the static-file rule first and 404 the route on refresh."
    )


def test_nginx_serves_the_directory_the_build_actually_writes() -> None:
    """Renaming one without the other leaves the bundle unreachable, which
    looks like a blank page rather than like a configuration mistake."""
    directory = assets_dir()
    assert re.search(rf"location\s+/{re.escape(directory)}/", read(NGINX)), (
        f"nginx has no `location /{directory}/` block, but the build writes there"
    )


def test_the_spa_fallback_exists() -> None:
    """Without it every client route 404s on refresh, which is the whole class
    of bug this file is about."""
    assert "try_files $uri $uri/ /index.html" in read(NGINX)


def test_a_missing_bundle_file_still_404s() -> None:
    """The fallback must not swallow genuinely missing assets: a bundle file
    served as HTML fails later, in a parser, with no useful message."""
    assert "try_files $uri =404" in read(NGINX)


def test_the_api_prefix_is_not_swallowed_by_the_fallback() -> None:
    """A mistyped API path must return a JSON 404, not the application shell
    with a 200."""
    assert re.search(r"location\s+/api/", read(NGINX))
