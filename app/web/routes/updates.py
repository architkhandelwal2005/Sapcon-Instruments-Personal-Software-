"""Writing an update on a task or lead, and the notifications page behind the bell."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import updates
from app.db import get_connection, release_connection
from app.web.auth import actor_of
from app.web.authz import employee_owns_lead, employee_owns_task
from app.web.templating import templates

router = APIRouter()

_OWNS = {"task": employee_owns_task, "lead": employee_owns_lead}


@router.post("/updates")
def post_update(request: Request, kind: str = Form(...), item_id: str = Form(...),
                body: str = Form(default="")):
    """An employee may write only on their own work - the same rule as seeing it."""
    if kind not in _OWNS:
        raise HTTPException(status_code=404)
    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not _OWNS[kind](conn, actor, item_id):
            raise HTTPException(status_code=404)
        updates.post(conn, kind, item_id, body, author_id=actor.entity_id, author_name=actor.name)
        conn.commit()
    finally:
        release_connection(conn)
    return RedirectResponse(f"/{kind}s/{item_id}#updates", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    actor = actor_of(request)
    conn = get_connection()
    try:
        items = updates.inbox(conn, actor.entity_id)
    finally:
        release_connection(conn)
    return templates.TemplateResponse(request, "notifications.html", {"items": items})


@router.post("/notifications/read")
def mark_all_read(request: Request):
    actor = actor_of(request)
    conn = get_connection()
    try:
        updates.mark_all_read(conn, actor.entity_id)
        conn.commit()
    finally:
        release_connection(conn)
    return RedirectResponse("/notifications", status_code=303)
