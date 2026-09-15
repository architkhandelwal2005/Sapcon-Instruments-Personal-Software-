"""Task dashboard: what's left to do, and who it's assigned to. A task's
assignee comes from the voice-note extraction naming an employee explicitly
(app.entity_resolution.employees.match_employee) - never guessed. Status is
just open/done, changed only by a human clicking here, same as leads.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, release_connection

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _employee_options(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, canonical_name from entities where entity_type = 'employee' order by canonical_name"
        )
        return [{"id": str(i), "canonical_name": n} for i, n in cur.fetchall()]


def _predicate(*, status, assigned_to) -> tuple[str, dict]:
    where = ["t.review_status <> 'rejected'"]
    params: dict = {}
    if status:
        where.append("t.status = %(status)s")
        params["status"] = status
    if assigned_to:
        where.append("t.assigned_to = %(assigned_to)s")
        params["assigned_to"] = assigned_to
    return " and ".join(where), params


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    status: Optional[str] = "open",
    assigned_to: Optional[str] = None,
):
    clause, params = _predicate(status=status, assigned_to=assigned_to)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select t.id, t.description, t.related_entity_id, re.canonical_name,
                       t.assigned_to, ae.canonical_name, t.due_date, t.status,
                       t.review_status, t.confidence
                from tasks t
                left join entities re on re.id = t.related_entity_id
                left join entities ae on ae.id = t.assigned_to
                where {clause}
                order by t.due_date nulls last
                """,
                params,
            )
            today = date.today()
            rows = []
            for tid, desc, reid, rename, aid, aname, due, tstatus, review_status, confidence in cur.fetchall():
                rows.append({
                    "id": str(tid), "description": desc,
                    "related_entity_id": str(reid) if reid else None, "related_entity_name": rename,
                    "assigned_to": str(aid) if aid else None, "assigned_name": aname,
                    "due_date": due, "status": tstatus, "review_status": review_status,
                    "confidence": confidence,
                    "overdue": bool(due and due < today and tstatus != "done"),
                })
        employees = _employee_options(conn)
    finally:
        release_connection(conn)

    active = {"status": status or "", "assigned_to": assigned_to or ""}
    return templates.TemplateResponse(
        request, "tasks.html",
        {"rows": rows, "employees": employees, "active": active},
    )


@router.post("/tasks/{task_id}/status")
def update_task_status(task_id: str, status: str = Form(...), back: str = Form(default="/tasks")):
    if status not in ("open", "done"):
        return RedirectResponse(back, status_code=303)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("update tasks set status = %s where id = %s", (status, task_id))
        conn.commit()
    finally:
        release_connection(conn)
    return RedirectResponse(back, status_code=303)
