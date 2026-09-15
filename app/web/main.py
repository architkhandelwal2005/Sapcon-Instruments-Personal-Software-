from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_connection, release_connection
from app.review import pending_capture_count, pending_count
from app.web.routes import ask, captures, contacts, entities, ingest, leads, meetings, review, tasks, whatsapp

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Sapcon CRM")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ingest before meetings: /meetings/new must not be caught by /meetings/{meeting_id}
app.include_router(ingest.router)
app.include_router(meetings.router)
app.include_router(entities.router)
app.include_router(review.router)
app.include_router(ask.router)
app.include_router(contacts.router)
app.include_router(leads.router)
app.include_router(tasks.router)
app.include_router(captures.router)
app.include_router(whatsapp.router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select m.id, m.meeting_date, pc.canonical_name, pc.region, m.review_status
                from meetings m
                left join entities pc on pc.id = m.primary_contact_id
                order by m.meeting_date desc
                """
            )
            rows = cur.fetchall()
        review_backlog = pending_count(conn) + pending_capture_count(conn)
    finally:
        release_connection(conn)

    meetings_list = [
        {
            "id": r[0], "meeting_date": r[1], "primary_contact_name": r[2],
            "primary_contact_region": r[3], "review_status": r[4],
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request, "home.html", {"meetings": meetings_list, "review_backlog": review_backlog}
    )
