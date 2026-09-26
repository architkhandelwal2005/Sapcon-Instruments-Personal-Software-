from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.db import get_connection, release_connection
from app.review import pending_capture_count, pending_count
from app.web.auth import COOKIE_NAME, load_actor
from app.web.policy import is_public, role_allows
from app.web.templating import templates
from app.web.routes import (
    admin, ask, captures, contacts, entities, ingest, leads, login, meetings, review, tasks, whatsapp,
)

BASE_DIR = Path(__file__).resolve().parent

# No /docs, /redoc or /openapi.json: nothing consumes this as an API, and an
# open schema advertises every route and form field of a CRM that is reachable
# from the internet because the WhatsApp webhook has to be.
app = FastAPI(title="Sapcon CRM", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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
app.include_router(login.router)
app.include_router(admin.router)


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every page needs a signed-in person, decided in one place so a route
    added later cannot ship open by forgetting a decorator."""
    path = request.url.path
    if is_public(path):
        return await call_next(request)

    conn = get_connection()
    try:
        actor = load_actor(conn, request.cookies.get(COOKIE_NAME))
    finally:
        release_connection(conn)

    if actor is None:
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
    if not role_allows(actor.role, path):
        return RedirectResponse("/tasks?error=You+do+not+have+access+to+that+page", status_code=303)

    request.state.actor = actor
    return await call_next(request)


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
        request, "home.html",
        {"meetings": meetings_list, "review_backlog": review_backlog},
    )
