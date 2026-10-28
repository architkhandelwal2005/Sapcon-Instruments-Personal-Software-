"""Everyone's work on one screen: who has what open, what is late, what has gone
quiet. The question the owner asks every morning, answered without picking
names one at a time from a filter."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import get_connection, release_connection
from app.web.routes.leads import STALE_AFTER_DAYS, _search as search_leads
from app.web.templating import templates

router = APIRouter()


def _row(name, entity_id=None):
    return {"id": entity_id, "name": name, "open_tasks": 0, "overdue": 0, "done_week": 0,
            "open_leads": 0, "stale_leads": 0, "last_seen": None}


@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request):
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
        {"rows": rows, "nobody": nobody, "stale_days": STALE_AFTER_DAYS},
    )
