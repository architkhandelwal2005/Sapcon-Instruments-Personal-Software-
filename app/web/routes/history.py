"""Undo, for every page at once.

An edit redirects back with ?undo=<change ids>, base.html shows a single Undo
button for whatever page that was, and the button posts here. So no page needs
undo code of its own, and adding a new kind of edit gets undo for free.

A form that changed several fields is undone as one: if any of them cannot be
put back - somebody has changed it again since - none of them are, rather than
leaving the record half-reverted.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import history
from app.db import get_connection, release_connection
from app.web.auth import actor_of

router = APIRouter()


def _safe_back(back: str) -> str:
    """Only ever a path on this site. A full URL here would let a crafted form
    send someone off to another site straight after they clicked Undo."""
    if not back.startswith("/") or back.startswith("//"):
        return "/"
    return back.split("?", 1)[0]


def with_undo(back: str, *change_ids) -> RedirectResponse:
    """Where an edit route sends the person afterwards: back where they were,
    with the Undo bar showing if anything actually changed."""
    url = _safe_back(back)
    ids = [str(i) for i in change_ids if i is not None]
    if ids:
        url += "?undo=" + ",".join(ids)
    return RedirectResponse(url, status_code=303)


@router.post("/history/undo")
def undo_changes(request: Request, ids: str = Form(...), back: str = Form(default="/")):
    actor = actor_of(request)
    change_ids = []
    for raw in ids.split(","):
        try:
            change_ids.append(int(raw))
        except ValueError:
            continue

    outcome = "missing"
    conn = get_connection()
    try:
        for change_id in change_ids:
            outcome = history.undo(conn, change_id, actor_id=actor.entity_id,
                                   may_undo_others=not actor.is_employee())
            if outcome != "done":
                conn.rollback()
                break
        else:
            conn.commit()
    finally:
        release_connection(conn)

    return RedirectResponse(f"{_safe_back(back)}?undone={outcome}", status_code=303)
