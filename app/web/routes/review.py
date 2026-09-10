from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection
from app.minutes.generate import fetch_meeting_minutes_data
from app.review import apply_decision, meeting_entities, pending_summary, rejected_items

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/review", response_class=HTMLResponse)
def review_index(request: Request):
    conn = get_connection()
    try:
        meetings = pending_summary(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "review.html", {"meetings": meetings})


@router.get("/review/{meeting_id}", response_class=HTMLResponse)
def review_meeting(request: Request, meeting_id: str, done: Optional[int] = None):
    conn = get_connection()
    try:
        data = fetch_meeting_minutes_data(conn, meeting_id)
        entities = meeting_entities(conn, meeting_id)
        rejected = rejected_items(conn, meeting_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "review_meeting.html",
        {"data": data, "entities": entities, "rejected": rejected, "done": done},
    )


@router.post("/review/{meeting_id}/item")
def review_item(
    meeting_id: str,
    kind: str = Form(...),
    item_id: str = Form(...),
    decision: str = Form(...),
    description: str = Form(default=""),
    role_tag: str = Form(default=""),
    due_date: str = Form(default=""),
):
    parsed_due = None
    if due_date.strip():
        try:
            parsed_due = datetime.strptime(due_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            parsed_due = None

    conn = get_connection()
    try:
        apply_decision(
            conn, kind, item_id, decision,
            description=(description if description.strip() else None),
            role_tag=(role_tag.strip() or None),
            due_date=parsed_due,
        )
        remaining = [m for m in pending_summary(conn) if m["meeting_id"] == meeting_id]
    finally:
        conn.close()

    if not remaining:
        return RedirectResponse(f"/review/{meeting_id}?done=1", status_code=303)
    return RedirectResponse(f"/review/{meeting_id}", status_code=303)
