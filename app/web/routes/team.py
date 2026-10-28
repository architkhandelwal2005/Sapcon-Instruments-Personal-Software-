"""Everyone's work on one screen: who has what open, what is late, what has gone
quiet. The question the owner asks every morning, answered without picking
names one at a time from a filter."""

import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.web.routes.leads import STALE_AFTER_DAYS, _search as search_leads
from app.web.templating import templates

router = APIRouter()


def _row(name, entity_id=None):
    return {"id": entity_id, "name": name, "open_tasks": 0, "overdue": 0, "done_week": 0,
            "open_leads": 0, "stale_leads": 0, "last_seen": None}


@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request, moved: str = ""):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select e.id, e.canonical_name,
                       (select max(greatest(s.created_at, s.last_seen_at))
                        from app_sessions s where s.entity_id = e.id)
                from entities e join app_users u on u.entity_id = e.id
                where u.role = 'employee' and not u.disabled
                """
            )
            people = {}
            for eid, name, seen in cur.fetchall():
                people[str(eid)] = _row(name, str(eid)) | {"last_seen": seen}
            nobody = _row("Not assigned to anyone")

            cur.execute(
                """
                select ta.employee_id, t.due_date < current_date
                from tasks t left join task_assignees ta on ta.task_id = t.id
                where t.status <> 'done' and t.review_status <> 'rejected'
                """
            )
            for eid, late in cur.fetchall():
                row = people.get(str(eid)) if eid else nobody
                if row is not None:
                    row["open_tasks"] += 1
                    row["overdue"] += bool(late)

            # Finished in the last 7 days and still finished - an undone "done"
            # is not work done.
            cur.execute(
                """
                select ta.employee_id, count(distinct c.item_id)
                from change_log c
                join tasks t on t.id = c.item_id and t.status = 'done'
                join task_assignees ta on ta.task_id = c.item_id
                where c.kind = 'task' and c.field = 'status' and c.after = '"done"'::jsonb
                  and c.undone_at is null and c.changed_at > now() - interval '7 days'
                group by 1
                """
            )
            for eid, n in cur.fetchall():
                if str(eid) in people:
                    people[str(eid)]["done_week"] = n

        for lead in search_leads(conn, "l.status = 'open'", {}):
            row = people.get(lead["assigned_to"]) if lead["assigned_to"] else nobody
            if row is not None:
                row["open_leads"] += 1
                row["stale_leads"] += lead["stale"]
    finally:
        release_connection(conn)

    rows = sorted(people.values(),
                  key=lambda r: (-r["overdue"], -r["stale_leads"], -r["open_tasks"], r["name"]))
    return templates.TemplateResponse(
        request, "team.html",
        {"rows": rows, "nobody": nobody, "stale_days": STALE_AFTER_DAYS,
         "everyone": sorted(people.values(), key=lambda r: r["name"]),
         # Only digits reach the page, so a crafted link cannot make it say anything.
         "moved": re.fullmatch(r"(\d+)-(\d+)", moved).groups() if re.fullmatch(r"\d+-\d+", moved) else None,
         "moved_refused": moved == "same"},
    )


@router.post("/team/handover")
def handover(request: Request, from_id: str = Form(...), to_id: str = Form(...)):
    """Move everything someone still has open to someone else - for leave, or
    for a person leaving. Finished work stays with whoever finished it, so the
    record of who did what is not rewritten. The new owner is told about each
    item by the same notices any assignment sends."""
    if not from_id or not to_id or from_id == to_id:
        return RedirectResponse("/team?moved=same", status_code=303)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select id, canonical_name from entities where entity_type = 'employee' "
                        "and id = any(%s::uuid[])", ([from_id, to_id],))
            names = {str(i): n for i, n in cur.fetchall()}
            if len(names) != 2:
                return RedirectResponse("/team?moved=same", status_code=303)

            # Tasks the new owner already shares just lose the old owner;
            # the rest change hands.
            cur.execute(
                """
                delete from task_assignees ta
                using tasks t
                where ta.task_id = t.id and t.status <> 'done' and ta.employee_id = %(f)s
                  and exists (select 1 from task_assignees o
                              where o.task_id = ta.task_id and o.employee_id = %(t)s)
                returning ta.task_id
                """,
                {"f": from_id, "t": to_id},
            )
            shared = cur.rowcount
            cur.execute(
                """
                update task_assignees ta set employee_id = %(t)s, name = %(n)s, seen_at = null
                from tasks t
                where ta.task_id = t.id and t.status <> 'done' and ta.employee_id = %(f)s
                returning ta.task_id
                """,
                {"f": from_id, "t": to_id, "n": names[to_id]},
            )
            moved = [str(r[0]) for r in cur.fetchall()]
            moved_tasks = len(moved)
            # Changed by update rather than insert, so the database's own
            # assignment notice does not fire; announce the moved ones here.
            cur.execute(
                """
                insert into notifications (recipient_id, kind, item_kind, item_id, body, url)
                select %(t)s, 'assigned', 'task', t.id,
                       'New task for you (from ' || %(fn)s || '): ' || left(t.description, 140),
                       '/tasks/' || t.id
                from tasks t where t.id = any(%(ids)s::uuid[])
                on conflict do nothing
                """,
                {"t": to_id, "fn": names[from_id], "ids": moved},
            )
            cur.execute("update leads set assigned_to = %s where assigned_to = %s and status = 'open'",
                        (to_id, from_id))
            moved_leads = cur.rowcount
        conn.commit()
    finally:
        release_connection(conn)
    return RedirectResponse(f"/team?moved={moved_tasks + shared}-{moved_leads}", status_code=303)
