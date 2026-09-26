from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.ingestion.pipeline import ingest_new_meeting
from app.web.helpers import save_and_transcribe
from app.web.auth import actor_of
from app.web.templating import templates

router = APIRouter()


@router.get("/meetings/new", response_class=HTMLResponse)
def new_meeting_form(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        request, "ingest.html", {"today": date.today().isoformat(), "error": error}
    )


@router.post("/meetings/new")
async def create_meeting(
    request: Request,
    meeting_date: str = Form(...),
    primary_contact: str = Form(default=""),
    location: str = Form(default=""),
    text: str = Form(default=""),
    audio: Optional[UploadFile] = File(default=None),
):
    try:
        mdate = datetime.strptime(meeting_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(f"/meetings/new?error={quote('Enter the meeting date as YYYY-MM-DD')}", status_code=303)

    transcript = text.strip()
    audio_path = None
    if audio is not None and audio.filename:
        transcribed, audio_path = await save_and_transcribe(audio)
        transcript = (transcript + "\n" + transcribed).strip() if transcript else transcribed

    if not transcript:
        return RedirectResponse(f"/meetings/new?error={quote('Add the recording or type the recap')}", status_code=303)

    actor = actor_of(request)
    conn = get_connection()
    try:
        res = ingest_new_meeting(
            conn, transcript, mdate,
            primary_contact_name=(primary_contact.strip() or None),
            location=(location.strip() or None),
            audio_path=audio_path,
            logged_by=actor.entity_id,
        )
    except Exception as exc:
        return RedirectResponse(f"/meetings/new?error={quote(str(exc)[:200])}", status_code=303)
    finally:
        release_connection(conn)

    # Review is the office person's screen; an employee is sent to the meeting
    # they just recorded, which is theirs to read because they logged it.
    landing = f"/meetings/{res.meeting_id}" if actor.is_employee() else f"/review/{res.meeting_id}"
    return RedirectResponse(landing, status_code=303)
