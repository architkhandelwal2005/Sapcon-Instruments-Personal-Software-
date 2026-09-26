"""Which roles may reach which pages.

One table, consulted by the middleware, so access is decided in a place someone
can read in full rather than scattered across twenty route functions.

The default is deny: a path nobody has listed is owner-only. A new route is
therefore locked until somebody makes a deliberate decision about it, which is
the opposite of the failure mode where a page ships open because its author did
not think about access.
"""

from typing import Iterable

ALL = ("owner", "office", "employee")
STAFF = ("owner", "office")
OWNER = ("owner",)

# Reachable without signing in. The webhook is authenticated differently - Meta
# signs every request, and the sender must be in whatsapp_senders.
PUBLIC_PATHS = frozenset({
    "/login",
    "/logout",
    "/enrol",
    "/health",
    "/whatsapp/webhook",
})

PUBLIC_PREFIXES = ("/static/",)

# Longest matching prefix wins, so "/meetings/new" can be more open than
# "/meetings". Order here is for reading; matching sorts by length.
POLICY: dict[str, tuple[str, ...]] = {
    "/": ALL,
    "/tasks": ALL,
    "/leads": ALL,
    "/meetings": ALL,
    "/meetings/new": ALL,
    "/captures/new": ALL,
    "/entities": ALL,
    "/contacts": ALL,
    "/ask": ALL,
    "/review": ALL,
    "/admin": OWNER,
}


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def allowed_roles(path: str) -> tuple[str, ...]:
    """The roles that may reach this path. Unlisted paths are owner-only."""
    best: tuple[str, ...] = OWNER
    best_len = -1
    for prefix, roles in POLICY.items():
        if _matches(path, prefix) and len(prefix) > best_len:
            best, best_len = roles, len(prefix)
    return best


def _matches(path: str, prefix: str) -> bool:
    if prefix == "/":
        return path == "/"
    return path == prefix or path.startswith(prefix + "/")


def role_allows(role: str, path: str) -> bool:
    return role in allowed_roles(path)


def unlisted_paths(paths: Iterable[str]) -> list[str]:
    """Routes that no policy entry covers, so they silently fall to owner-only.
    Used by scripts/audit_routes.py to catch a new route before it ships."""
    return sorted(
        p for p in paths
        if not is_public(p) and not any(_matches(_concrete(p), prefix) for prefix in POLICY)
    )


def _concrete(route_path: str) -> str:
    """'/leads/{lead_id}' behaves like '/leads/x' for prefix matching."""
    return route_path.replace("{", "").replace("}", "")
