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

# Two tables. EXACT wins over PREFIX, which lets one page differ from the ones
# beneath it: the meeting log lists every customer visit and is staff-only,
# while a single meeting is reachable by the employee who recorded it, decided
# by a row check in the handler. Among prefixes, the longest match wins.
POLICY_EXACT: dict[str, tuple[str, ...]] = {
    "/": STAFF,             # the home page is a list of every meeting
    "/meetings": STAFF,     # the meeting log, likewise
}

POLICY: dict[str, tuple[str, ...]] = {
    # An employee gets their own work and the customers they reach through it.
    "/tasks": ALL,
    "/leads": ALL,
    "/meetings": ALL,           # a single meeting; the log itself is EXACT above
    "/captures/new": ALL,
    "/entities": ALL,           # a row check in the handler decides which ones

    # The whole book and the relationship graph are the asset that leaves with
    # someone who leaves.
    "/contacts": STAFF,
    "/review": STAFF,

    # Free-text questions over partially-scoped retrieval is the easiest way to
    # leak the whole book: one missed filter in one query and "summarise our
    # biggest customers" answers it. Revisit when retrieval is scoped and
    # audited end to end.
    "/ask": STAFF,

    "/admin": OWNER,
}


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def allowed_roles(path: str) -> tuple[str, ...]:
    """The roles that may reach this path. Unlisted paths are owner-only."""
    if path in POLICY_EXACT:
        return POLICY_EXACT[path]
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
        if not is_public(p)
        and p not in POLICY_EXACT
        and not any(_matches(_concrete(p), prefix) for prefix in POLICY)
    )


def _concrete(route_path: str) -> str:
    """'/leads/{lead_id}' behaves like '/leads/x' for prefix matching."""
    return route_path.replace("{", "").replace("}", "")
