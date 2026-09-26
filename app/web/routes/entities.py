
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.db import get_connection, release_connection
from app.entity_resolution.review_queue import fetch_flags_for_entity
from app.graph.entity_view import fetch_entity_connections
from app.minutes.generate import TaskRow, fetch_meeting_minutes_data, fetch_task_assignees
from app.web.helpers import with_overdue_flags
from app.web.auth import actor_of
from app.web.authz import employee_can_see_entity, visible_meeting_clause
from app.web.templating import templates

router = APIRouter()


def fetch_entity(conn, entity_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "select canonical_name, entity_type, aliases, region, title, phone, email, "
            "review_status, notes from entities where id = %s",
            (entity_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No entity found with id {entity_id}")
        return {
            "id": entity_id, "canonical_name": row[0], "entity_type": row[1], "aliases": row[2] or [],
            "region": row[3], "title": row[4], "phone": row[5], "email": row[6],
            "review_status": row[7], "notes": row[8],
        }


def fetch_interaction_history(conn, entity_id: str, *, actor=None) -> list[dict]:
    """Meetings that touch this entity via a relation OR a task - a task
    with no relation is still a real meeting, and open commitments must
    never be able to disagree with interaction history about whether one
    exists (a "no meetings yet" next to a real open commitment would read
    as if nothing is owed, on the one screen meant to prevent exactly
    that). Works uniformly for a person (who's usually also the
    primary_contact of their own direct meetings) and a company (which
    only ever appears via relations/tasks, never as primary_contact
    itself). Also the activity history behind a lead's profile - who
    logged each call, reused as-is via entity_id, no lead-specific query.

    `actor` limits the history for an employee to meetings they recorded or
    attended. Owning a lead does not make the owner's private notes from a
    visit they were not on theirs to read."""
    visible, visible_params = visible_meeting_clause(actor) if actor else ("true", {})
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select distinct m.id, m.meeting_date, pc.canonical_name, lb.canonical_name
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            left join entities lb on lb.id = m.logged_by
            where {visible} and m.id in (
                select meeting_id from relations
                where (source_id = %(entity_id)s or target_id = %(entity_id)s)
                  and status = 'active' and review_status <> 'rejected'
                union
                select meeting_id from tasks where related_entity_id = %(entity_id)s and review_status <> 'rejected'
            )
            order by m.meeting_date desc
            """,
            {"entity_id": entity_id, **visible_params},
        )
        return [
            {"id": str(mid), "meeting_date": meeting_date, "primary_contact_name": pc_name, "logged_by_name": lb_name}
            for mid, meeting_date, pc_name, lb_name in cur.fetchall()
        ]


def _fetch_open_commitments(conn, entity_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, description, due_date, status
            from tasks
            where related_entity_id = %(entity_id)s and status = 'open' and review_status <> 'rejected'
            order by due_date nulls last
            """,
            {"entity_id": entity_id},
        )
        found = cur.fetchall()
    owners = fetch_task_assignees(conn, [str(r[0]) for r in found])
    rows = [
        TaskRow(
            description=description, related_entity_name=None, related_entity_id=entity_id,
            due_date=due_date, status=status, confidence=None, review_status="", source_quote=None,
            task_id=str(tid), assignees=owners.get(str(tid), []),
        )
        for tid, description, due_date, status in found
    ]
    return with_overdue_flags(rows)


@router.get("/entities/{entity_id}", response_class=HTMLResponse)
def view_entity(request: Request, entity_id: str):
    actor = actor_of(request)
    conn = get_connection()
    try:
        if actor.is_employee() and not employee_can_see_entity(conn, actor, entity_id):
            # 404 rather than 403: which customers exist is itself the asset.
            raise HTTPException(status_code=404, detail="No such contact")
        entity = fetch_entity(conn, entity_id)
        history = fetch_interaction_history(conn, entity_id, actor=actor)
        commitments = _fetch_open_commitments(conn, entity_id)
        connections = fetch_entity_connections(conn, entity_id)
        review_flags = fetch_flags_for_entity(conn, entity_id)
        last_meeting = fetch_meeting_minutes_data(conn, history[0]["id"]) if history else None
    finally:
        release_connection(conn)

    return templates.TemplateResponse(
        request,
        "entity_profile.html",
        {
            "entity": entity,
            "history": history,
            "commitments": commitments,
            "connections": connections,
            "review_flags": review_flags,
            "last_meeting": last_meeting,
        },
    )


@router.get("/entities/{entity_id}/contour", response_class=HTMLResponse)
def view_contour(request: Request, entity_id: str):
    """Grouped list/table by relation type - not a visual graph, per
    instruction. Reuses the same fetch_entity_connections() as the
    profile's condensed view, just grouped rather than flat, so the two
    screens can never disagree about what's connected.

    Staff only: this is the relationship map - who introduces whom, which
    consultant sits behind which order - and is the most concentrated form of
    the thing that leaves with someone who leaves."""
    actor = actor_of(request)
    if actor.is_employee():
        raise HTTPException(status_code=404, detail="No such page")
    conn = get_connection()
    try:
        entity = fetch_entity(conn, entity_id)
        connections = fetch_entity_connections(conn, entity_id)
    finally:
        release_connection(conn)

    # Jinja's groupby filter requires pre-sorted input. Untagged edges group
    # under "" and render as "untagged".
    connections_sorted = sorted(connections, key=lambda c: (c.role_tag or "", c.other_name))

    return templates.TemplateResponse(
        request,
        "contour.html",
        {
            "entity": entity,
            "connections": connections_sorted,
        },
    )
