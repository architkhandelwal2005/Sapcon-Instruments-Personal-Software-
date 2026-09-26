"""Check that every route is either public on purpose or covered by the access
policy, and print who can reach what.

The policy denies by default, so an uncovered route is owner-only rather than
open - but that is a silent decision nobody made. This makes it loud, and is
meant to be run before a deploy.

Exit code 1 when something is uncovered, so it can gate a release.

Usage: audit_routes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.web.main import app
from app.web.policy import POLICY, allowed_roles, is_public, unlisted_paths


def _walk(routes, prefix: str = "") -> set[tuple[str, str]]:
    """Every (path, methods) pair, including those inside included routers -
    this FastAPI keeps a router as one nested entry rather than flattening it,
    and an audit that missed them would report a clean sheet while most of the
    app went unchecked."""
    found: set[tuple[str, str]] = set()
    for route in routes:
        # An included router appears as one opaque entry that holds the real
        # routes on `original_router`.
        included = getattr(route, "original_router", None)
        nested = getattr(included, "routes", None) or getattr(route, "routes", None)
        if nested:
            found |= _walk(nested, prefix + getattr(route, "prefix", ""))
            continue
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            shown = ",".join(sorted(m for m in methods if m not in ("HEAD", "OPTIONS")))
            found.add((prefix + path, shown))
    return found


def main() -> None:
    routes = sorted(_walk(app.routes))

    print(f"{'METHOD':10}{'PATH':44}WHO")
    for path, methods in routes:
        if is_public(path):
            who = "public"
        else:
            who = ", ".join(allowed_roles(path.replace("{", "").replace("}", "")))
        print(f"{methods:10}{path:44}{who}")

    uncovered = unlisted_paths(p for p, _ in routes)
    if uncovered:
        print("\nNOT COVERED by any policy entry (falls back to owner-only):")
        for path in uncovered:
            print(f"  {path}")
        print("\nAdd each to POLICY in app/web/policy.py, or to PUBLIC_PATHS if it is "
              "meant to be reachable without signing in.")
        raise SystemExit(1)

    print(f"\nAll {len(routes)} routes covered by {len(POLICY)} policy entries.")


if __name__ == "__main__":
    main()
