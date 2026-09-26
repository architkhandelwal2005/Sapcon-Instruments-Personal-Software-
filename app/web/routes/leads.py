"""Lead tracking: who owns each prospect, its status, and its call history. No
invented sales-funnel stages - open/converted/dropped, matching how the team
actually works. Status only ever changes by a human clicking a button here; nothing
here ever flips a status automatically. "Dropped" keeps the row and every call ever
logged against it - same as a rejected review item, nothing is destroyed.

A lead's activity history is not a separate table - it's every meeting touching the
lead's entity, reusing fetch_interaction_history() as-is.
"""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.web.routes.entities import fetch_entity, fetch_interaction_history
from app.web.auth import actor_of
from app.web.authz import employee_owns_lead
from app.web.templating import templates

router = APIRouter()

STATUSES = ("open", "converted", "dropped")
STALE_AFTER_DAYS = 14


def _employee_options(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, canonical_name from entities where entity_type = 'employee' order by canonical_name"
        )
        return [{"id": str(i), "canonical_name": n} for i, n in cur.fetchall()]


def _predicate(*, status, assigned_to, source, actor=None) -> tuple[str, dict]:
    """An employee sees the leads allotted to them, whatever the query string
    says - forced, not defaulted, so editing the URL changes nothing."""
    if actor is not None and actor.is_employee():
        assigned_to = actor.entity_id
    where = ["1=1"]
    params: dict = {}
    if status:
        where.append("l.status = %(status)s")
        params["status"] = status
    if assigned_to:
        where.append("l.assigned_to = %(assigned_to)s")
        params["assigned_to"] = assigned_to
    if source:
        where.append("l.source = %(source)s")
        params["source"] = source
    return " and ".join(where), params


def _rows_with_staleness(rows: list[dict]) -> list[dict]:
    today = date.today()
    for r in rows:
        last = r["last_activity"] or (r["created_at"].date() if r["created_at"] else None)
        r["stale"] = bool(last is None or (today - last).days >= STALE_AFTER_DAYS) if r["status"] == "open" else False
        r["last_activity_display"] = r["last_activity"]
    return rows


def _search(conn, clause: str, params: dict) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select l.id, l.entity_id, e.canonical_name, e.entity_type, l.assigned_to, ae.canonical_name,
                   l.status, l.source, l.next_follow_up_due, l.notes, l.created_at,
                   (select max(m.meeting_date) from meetings m where m.id in (
                        select meeting_id from relations
                        where (source_id = l.entity_id or target_id = l.entity_id) and review_status <> 'rejected'
                        union
                        select meeting_id from tasks where related_entity_id = l.entity_id and review_status <> 'rejected'
                   )) as last_activity
            from leads l
            join entities e on e.id = l.entity_id
            left join entities ae on ae.id = l.assigned_to
            where {clause}
            order by l.next_follow_up_due nulls last, l.created_at desc
            """,
            params,
        )
        rows = [
            {
                "id": str(lid), "entity_id": str(eid), "canonical_name": name, "entity_type": etype,
                "assigned_to": (str(aid) if aid else None), "assigned_name": aname,
                "status": status, "source": source, "next_follow_up_due": due, "notes": notes,
                "created_at": created_at, "last_activity": last_activity,
            }
            for lid, eid, name, etype, aid, aname, status, source, due, notes, created_at, last_activity in cur.fetchall()
        ]
    return _rows_with_staleness(rows)


@router.get("/leads", response_class=HTMLResponse)
def leads_page(
    request: Request,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    source: Optional[str] = None,
):
    actor = actor_of(request)
    clause, params = _predicate(status=status, assigned_to=assigned_to, source=source, actor=actor)
    conn = get_connection()
    try:
        rows = _search(conn, clause, params)
        employees = [] if actor.is_employee() else _employee_options(conn)
        with conn.cursor() as cur:
            cur.execute("select distinct source from leads where source is not null order by source")
            sources = [r[0] for r in cur.fetchall()]
    finally:
        release_connection(conn)

    active = {"status": status or "", "source": source or "",
              "assigned_to": actor.entity_id if actor.is_employee() else (assigned_to or "")}
    return templates.TemplateResponse(
        request,
        "leads.html",
        {
            "rows": rows,
            "statuses": STATUSES,
            "employees": employees,
            "sources": sources,
            "active": active,
            "stale_days": STALE_AFTER_DAYS,
        },
    )


@router.get("/leads/new", response_class=HTMLResponse)
def new_lead_form(request: Request, error: Optional[str] = None):
    conn = get_connection()
    try:
        employees = _employee_options(conn)
    finally:
        release_connection(conn)
    return templates.TemplateResponse(request, "lead_new.html", {"employees": employees, "error": error})


@router.post("/leads/new")
def create_lead(
    entity_name: str = Form(...),
    entity_type: str = Form(...),
    assigned_to: str = Form(default=""),
    source: str = Form(default="manual"),
    next_follow_up_due: str = Form(default=""),
    notes: str = Form(default=""),
):
    name = entity_name.strip()
    if not name:
        return RedirectResponse("/leads/new?error=Enter a name", status_code=303)

    due = None
    if next_follow_up_due.strip():
        try:
            due = datetime.strptime(next_follow_up_due.strip(), "%Y-%m-%d").date()
        except ValueError:
            due = None

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # A human is explicitly naming this entity here - exact match or create,
            # no fuzzy/LLM resolution (that's for extracting from ambiguous audio,
            # not for someone directly typing a name into a form).
            cur.execute(
                "select id from entities where lower(canonical_name) = %s and entity_type = %s",
                (name.lower(), entity_type),
            )
            row = cur.fetchone()
            if row:
                entity_id = row[0]
            else:
                cur.execute(
                    "insert into entities (canonical_name, entity_type, source, review_status) "
                    "values (%s, %s, 'manual', 'confirmed') returning id",
                    (name, entity_type),
                )
                entity_id = cur.fetchone()[0]

            cur.execute(
                "insert into leads (entity_id, assigned_to, source, next_follow_up_due, notes) "
                "values (%s, %s, %s, %s, %s) returning id",
                (entity_id, (assigned_to or None), (source.strip() or "manual"), due, (notes.strip() or None)),
            )
            (lead_id,) = cur.fetchone()
        conn.commit()
    finally:
        release_connection(conn)

    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(request: Request, lead_id: str, done: Optional[int] = None):
    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not employee_owns_lead(conn, actor, lead_id):
            # 404, not 403: "this lead exists but is not yours" is itself a fact
            # about who the company is talking to.
            raise HTTPException(status_code=404, detail="No such lead")
        with conn.cursor() as cur:
            cur.execute(
                """
                select l.entity_id, l.assigned_to, ae.canonical_name, l.status, l.source,
                       l.next_follow_up_due, l.notes, l.created_at, l.status_changed_at, sce.canonical_name
                from leads l
                left join entities ae on ae.id = l.assigned_to
                left join entities sce on sce.id = l.status_changed_by
                where l.id = %s
                """,
                (lead_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No lead {lead_id!r}")
            (entity_id, assigned_to, assigned_name, status, source,
             next_follow_up_due, notes, created_at, status_changed_at, status_changed_by_name) = row

        entity = fetch_entity(conn, str(entity_id))
        history = fetch_interaction_history(conn, str(entity_id), actor=actor)
        employees = [] if actor.is_employee() else _employee_options(conn)
    finally:
        release_connection(conn)

    lead = {
        "id": lead_id, "entity": entity, "assigned_to": (str(assigned_to) if assigned_to else None),
        "assigned_name": assigned_name, "status": status, "source": source,
        "next_follow_up_due": next_follow_up_due, "notes": notes, "created_at": created_at,
        "status_changed_at": status_changed_at, "status_changed_by_name": status_changed_by_name,
    }
    return templates.TemplateResponse(
        request,
        "lead_detail.html",
        {"lead": lead, "history": history, "employees": employees, "statuses": STATUSES, "done": done},
    )


@router.post("/leads/{lead_id}/status")
def update_lead_status(
    request: Request,
    lead_id: str,
    status: str = Form(...),
    changed_by: str = Form(default=""),
    next_follow_up_due: str = Form(default=""),
    notes: str = Form(default=""),
):
    if status not in STATUSES:
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    due = None
    if next_follow_up_due.strip():
        try:
            due = datetime.strptime(next_follow_up_due.strip(), "%Y-%m-%d").date()
        except ValueError:
            due = None

    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not employee_owns_lead(conn, actor, lead_id):
            return RedirectResponse("/leads?error=That+lead+is+not+yours", status_code=303)
        with conn.cursor() as cur:
            cur.execute(
                "update leads set status = %s, status_changed_at = now(), status_changed_by = %s, "
                "next_follow_up_due = coalesce(%s, next_follow_up_due), "
                "notes = case when %s <> '' then %s else notes end "
                "where id = %s",
                (status, (changed_by or None), due, notes.strip(), notes.strip(), lead_id),
            )
        conn.commit()
    finally:
        release_connection(conn)

    return RedirectResponse(f"/leads/{lead_id}?done=1", status_code=303)
