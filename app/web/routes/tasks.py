"""Task dashboard: what's left to do, and who owns it. Owners come from the
voice-note extraction naming staff explicitly (task_assignees, matched by
app.entity_resolution.employees.match_employee) - never guessed; a name that
didn't match the roster is still shown as heard. Status is just open/done,
changed only by a human clicking here, same as leads.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.minutes.generate import fetch_task_assignees
from app.web.auth import actor_of
from app import history, updates
from app.web.routes.history import with_undo
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
                       t.due_date, t.status, t.review_status, t.confidence, t.meeting_id, t.due_assumed
                from tasks t
                left join entities re on re.id = t.related_entity_id
                where {clause}
                order by t.due_date nulls last
                """,
                params,
            )
            found = cur.fetchall()
        if actor.is_employee() and found:
            # Their own list, on screen in front of them: that is seeing it.
            with conn.cursor() as cur:
                cur.execute("update task_assignees set seen_at = now() where employee_id = %s "
                            "and seen_at is null and task_id = any(%s::uuid[])",
                            (actor.entity_id, [str(r[0]) for r in found]))
            conn.commit()
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
                "due_assumed": due_assumed,
            }
            for tid, desc, reid, rename, due, tstatus, review_status, confidence, mid, due_assumed in found
        ]
        notes = updates.counts(conn, "task", [r["id"] for r in rows])
        for r in rows:
            r["updates"] = notes.get(r["id"], 0)
        groups = _group_by_note(conn, rows, actor)
        employees = [] if actor.is_employee() else _employee_options(conn)
    finally:
        release_connection(conn)

    active = {"status": status or "",
              "assigned_to": actor.entity_id if actor.is_employee() else (assigned_to or "")}
    return templates.TemplateResponse(
        request, "tasks.html",
        {"groups": groups, "employees": employees, "active": active},
    )


def _progress(conn, meeting_ids: list[str], actor) -> dict[str, dict]:
    """For each note, how many of its tasks are done. Counted over every task
    the note produced, not just the ones on screen - "4 of 5 done" has to stay
    true while the list is filtered to open work. An employee counts only
    their own."""
    if not meeting_ids:
        return {}
    mine = actor is not None and actor.is_employee()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select t.meeting_id, m.meeting_date, count(*), count(*) filter (where t.status = 'done')
            from tasks t join meetings m on m.id = t.meeting_id
            where t.meeting_id = any(%(ids)s::uuid[]) and t.review_status <> 'rejected'
              {"and exists (select 1 from task_assignees ta where ta.task_id = t.id and ta.employee_id = %(me)s)" if mine else ""}
            group by t.meeting_id, m.meeting_date
            """,
            {"ids": meeting_ids, "me": actor.entity_id if mine else None},
        )
        return {str(mid): {"date": d, "total": n, "done": done} for mid, d, n, done in cur.fetchall()}


def _group_by_note(conn, rows: list[dict], actor) -> list[dict]:
    """Tasks from one voice note shown together, under how far along they are.
    A note that gave five instructions is one piece of work to the person who
    gave them; five unrelated rows hid that one of them was still open.

    Groups keep the order of their earliest task, so the most urgent work is
    still at the top."""
    progress = _progress(conn, sorted({r["meeting_id"] for r in rows if r["meeting_id"]}), actor)
    groups: dict[str, dict] = {}
    for r in rows:
        p = progress.get(r["meeting_id"] or "")
        key = r["meeting_id"] if p and p["total"] > 1 else r["id"]
        groups.setdefault(key, {"progress": p if p and p["total"] > 1 else None,
                                "meeting_id": r["meeting_id"], "rows": []})["rows"].append(r)
    return list(groups.values())


def _sibling_tasks(conn, task_id: str, meeting_id: Optional[str], actor) -> list[dict]:
    if not meeting_id:
        return []
    mine = actor.is_employee()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select t.id, t.description, t.status
            from tasks t
            where t.meeting_id = %(m)s and t.review_status <> 'rejected'
              {"and exists (select 1 from task_assignees ta where ta.task_id = t.id and ta.employee_id = %(me)s)" if mine else ""}
            order by t.due_date nulls last, t.description
            """,
            {"m": meeting_id, "me": actor.entity_id},
        )
        return [{"id": str(i), "description": d, "status": s, "current": str(i) == task_id}
                for i, d, s in cur.fetchall()]


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: str):
    """One task: what, for whom, by when, how far along the rest of its note
    is, and the updates people have written on it."""
    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not employee_owns_task(conn, actor, task_id):
            raise HTTPException(status_code=404, detail="No such task")
        with conn.cursor() as cur:
            # The first time an owner opens it is when they have seen it.
            cur.execute("update task_assignees set seen_at = now() "
                        "where task_id = %s and employee_id = %s and seen_at is null",
                        (task_id, actor.entity_id))
            cur.execute(
                """
                select t.description, t.related_entity_id, re.canonical_name, t.due_date,
                       t.status, t.review_status, t.meeting_id, m.meeting_date, t.due_assumed
                from tasks t
                left join entities re on re.id = t.related_entity_id
                left join meetings m on m.id = t.meeting_id
                where t.id = %s
                """,
                (task_id,),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such task")
        desc, reid, rename, due, tstatus, review_status, mid, mdate, due_assumed = row
        task = {
            "id": task_id, "description": desc,
            "related_entity_id": str(reid) if reid else None, "related_entity_name": rename,
            "due_date": due, "status": tstatus, "review_status": review_status,
            "meeting_id": str(mid) if mid else None, "meeting_date": mdate,
            "due_assumed": due_assumed,
            "assignees": fetch_task_assignees(conn, [task_id]).get(task_id, []),
            "overdue": bool(due and due < date.today() and tstatus != "done"),
        }
        siblings = _sibling_tasks(conn, task_id, task["meeting_id"], actor)
        thread = updates.for_item(conn, "task", task_id)
        changes = history.recent(conn, "task", task_id)
        updates.mark_item_read(conn, actor.entity_id, "task", task_id)
        conn.commit()
    finally:
        release_connection(conn)

    return templates.TemplateResponse(
        request, "task_detail.html",
        {"task": task, "siblings": siblings if len(siblings) > 1 else [],
         "siblings_done": sum(s["status"] == "done" for s in siblings),
         "thread": thread, "changes": changes, "kind": "task", "item_id": task_id},
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
        change_id = history.change(conn, "task", task_id, "status", status,
                                   actor_id=actor.entity_id)
        conn.commit()
    finally:
        release_connection(conn)
    return with_undo(back, change_id)


@router.post("/tasks/{task_id}/assign")
def reassign_task(request: Request, task_id: str, employee_id: str = Form(...),
                  back: str = Form(default="/tasks")):
    """Hand a task to someone, or take its owner off. Staff only: an employee
    sees only their own tasks, and passing work to someone else is not theirs
    to decide."""
    actor = actor_of(request)
    if actor.is_employee():
        return RedirectResponse("/tasks?error=Only+the+office+can+reassign+work", status_code=303)
    if not employee_id:
        return RedirectResponse(back, status_code=303)

    conn = get_connection()
    try:
        if employee_id == "none":
            owners = []
        else:
            with conn.cursor() as cur:
                cur.execute("select canonical_name from entities where id = %s "
                            "and entity_type = 'employee'", (employee_id,))
                row = cur.fetchone()
            if row is None:
                conn.rollback()
                return with_undo(back)
            owners = [{"employee_id": employee_id, "name": row[0]}]
        change_id = history.change(conn, "task", task_id, "owners", owners,
                                   actor_id=actor.entity_id)
        conn.commit()
    finally:
        release_connection(conn)
    return with_undo(back, change_id)
