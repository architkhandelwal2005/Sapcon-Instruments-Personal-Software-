from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection
from app.graph.entity_view import fetch_entity_connections
from app.minutes.generate import TaskRow, fetch_meeting_minutes_data
from app.web.helpers import with_overdue_flags

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _fetch_entity(conn, entity_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("select canonical_name, entity_type, aliases from entities where id = %s", (entity_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No entity found with id {entity_id}")
        return {"id": entity_id, "canonical_name": row[0], "entity_type": row[1], "aliases": row[2] or []}


def _fetch_interaction_history(conn, entity_id: str) -> list[dict]:
    """Meetings that mention this entity via any relation - works uniformly
    for a person (who's usually also the primary_contact of their own
    direct meetings) and a company (which only ever appears via relations,
    never as primary_contact itself)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct m.id, m.meeting_date, pc.canonical_name
            from meetings m
            join relations r on r.meeting_id = m.id and r.status = 'active'
            left join entities pc on pc.id = m.primary_contact_id
            where r.source_id = %(entity_id)s or r.target_id = %(entity_id)s
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
            "last_meeting": last_meeting,
        },
    )
