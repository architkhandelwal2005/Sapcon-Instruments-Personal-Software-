from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection
from app.entity_resolution.review_queue import fetch_flags_for_entity
from app.graph.entity_view import fetch_entity_connections
from app.minutes.generate import TaskRow, fetch_meeting_minutes_data
from app.web.helpers import with_overdue_flags

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _fetch_entity(conn, entity_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("select canonical_name, entity_type, aliases, region from entities where id = %s", (entity_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No entity found with id {entity_id}")
        return {"id": entity_id, "canonical_name": row[0], "entity_type": row[1], "aliases": row[2] or [], "region": row[3]}


def _fetch_interaction_history(conn, entity_id: str) -> list[dict]:
    """Meetings that touch this entity via a relation OR a task - a task
    with no relation is still a real meeting, and open commitments must
    never be able to disagree with interaction history about whether one
    exists (a "no meetings yet" next to a real open commitment would read
    as if nothing is owed, on the one screen meant to prevent exactly
    that). Works uniformly for a person (who's usually also the
    primary_contact of their own direct meetings) and a company (which
    only ever appears via relations/tasks, never as primary_contact
    itself)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct m.id, m.meeting_date, pc.canonical_name
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            where m.id in (
                select meeting_id from relations
                where (source_id = %(entity_id)s or target_id = %(entity_id)s) and status = 'active'
                union
                select meeting_id from tasks where related_entity_id = %(entity_id)s
            )
            order by m.meeting_date desc
            """,
            {"entity_id": entity_id},
        )
        return [{"id": str(mid), "meeting_date": meeting_date, "primary_contact_name": pc_name} for mid, meeting_date, pc_name in cur.fetchall()]


def _fetch_open_commitments(conn, entity_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select description, due_date, status
            from tasks
            where related_entity_id = %(entity_id)s and status = 'open'
            order by due_date nulls last
            """,
            {"entity_id": entity_id},
        )
        rows = [TaskRow(description, None, entity_id, due_date, status) for description, due_date, status in cur.fetchall()]
        return with_overdue_flags(rows)


@router.get("/entities/{entity_id}", response_class=HTMLResponse)
def view_entity(request: Request, entity_id: str):
    conn = get_connection()
    try:
        entity = _fetch_entity(conn, entity_id)
        history = _fetch_interaction_history(conn, entity_id)
        commitments = _fetch_open_commitments(conn, entity_id)
        connections = fetch_entity_connections(conn, entity_id)
        review_flags = fetch_flags_for_entity(conn, entity_id)
        last_meeting = fetch_meeting_minutes_data(conn, history[0]["id"]) if history else None
    finally:
        conn.close()

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
    screens can never disagree about what's connected."""
    conn = get_connection()
    try:
        entity = _fetch_entity(conn, entity_id)
        connections = fetch_entity_connections(conn, entity_id)
    finally:
        conn.close()

    # Jinja's groupby filter requires pre-sorted input.
    connections_sorted = sorted(connections, key=lambda c: (c.relation_type, c.other_name))

    return templates.TemplateResponse(
        request,
        "contour.html",
        {
            "entity": entity,
            "connections": connections_sorted,
        },
    )
