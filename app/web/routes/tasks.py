"""Task dashboard: what's left to do, and who owns it. Owners come from the
voice-note extraction naming staff explicitly (task_assignees, matched by
app.entity_resolution.employees.match_employee) - never guessed; a name that
didn't match the roster is still shown as heard. Status is just open/done,
changed only by a human clicking here, same as leads.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.minutes.generate import fetch_task_assignees
from app.web.auth import actor_of
from app.web.authz import employee_owns_task
from app.web.templating import templates

router = APIRouter()


def _employee_options(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, canonical_name from entities where entity_type = 'employee' order by canonical_name"
        )
        return [{"id": str(i), "canonical_name": n} for i, n in cur.fetchall()]


def _predicate(*, status, assigned_to, actor=None) -> tuple[str, dict]:
    """An employee sees their own tasks, whatever the query string says - the
    filter is forced rather than defaulted, so editing the URL changes
    nothing."""
    if actor is not None and actor.is_employee():
        assigned_to = actor.entity_id
    where = ["t.review_status <> 'rejected'"]
    params: dict = {}
    if status:
        where.append("t.status = %(status)s")
        params["status"] = status
    if assigned_to == "none":
        where.append("not exists (select 1 from task_assignees ta where ta.task_id = t.id)")
    elif assigned_to:
        where.append("exists (select 1 from task_assignees ta where ta.task_id = t.id and ta.employee_id = %(assigned_to)s)")
        params["assigned_to"] = assigned_to
    return " and ".join(where), params


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    status: Optional[str] = "open",
    assigned_to: Optional[str] = None,
):
    actor = actor_of(request)
    clause, params = _predicate(status=status, assigned_to=assigned_to, actor=actor)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select t.id, t.description, t.related_entity_id, re.canonical_name,
                       t.due_date, t.status, t.review_status, t.confidence, t.meeting_id
                from tasks t
                left join entities re on re.id = t.related_entity_id
                where {clause}
                order by t.due_date nulls last
                """,
                params,
            )
            found = cur.fetchall()
        owners = fetch_task_assignees(conn, [str(r[0]) for r in found])
        today = date.today()
        rows = [
            {
                "id": str(tid), "description": desc,
                "related_entity_id": str(reid) if reid else None, "related_entity_name": rename,
                "assignees": owners.get(str(tid), []),
                "due_date": due, "status": tstatus, "review_status": review_status,
                "confidence": confidence, "meeting_id": str(mid) if mid else None,
                "overdue": bool(due and due < today and tstatus != "done"),
            }
            for tid, desc, reid, rename, due, tstatus, review_status, confidence, mid in found
        ]
        employees = [] if actor.is_employee() else _employee_options(conn)
    finally:
        release_connection(conn)

    active = {"status": status or "",
              "assigned_to": actor.entity_id if actor.is_employee() else (assigned_to or "")}
    return templates.TemplateResponse(
        request, "tasks.html",
        {"rows": rows, "employees": employees, "active": active},
    )


@router.post("/tasks/{task_id}/status")
def update_task_status(request: Request, task_id: str, status: str = Form(...),
                       back: str = Form(default="/tasks")):
    if status not in ("open", "done"):
        return RedirectResponse(back, status_code=303)
    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not employee_owns_task(conn, actor, task_id):
            return RedirectResponse("/tasks?error=That+task+is+not+yours", status_code=303)
        with conn.cursor() as cur:
            cur.execute("update tasks set status = %s where id = %s", (status, task_id))
        conn.commit()
    finally:
        release_connection(conn)
    return RedirectResponse(back, status_code=303)
