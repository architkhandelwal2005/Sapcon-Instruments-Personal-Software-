from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection
from app.ingestion.pipeline import append_correction
from app.minutes.generate import fetch_meeting_minutes_data
from app.web.helpers import with_overdue_flags

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/meetings/{meeting_id}", response_class=HTMLResponse)
def view_meeting(
    request: Request,
    meeting_id: str,
    corrected: Optional[int] = None,
    error: Optional[str] = None,
    flagged: Optional[str] = None,
):
    conn = get_connection()
    try:
        data = fetch_meeting_minutes_data(conn, meeting_id)
    finally:
        conn.close()

    flash = None
    flash_error = False
    if corrected:
        flash = "Correction added."
        if flagged:
            flash += f" Needs review: {flagged} (couldn't confidently match, created as new - see the review queue)."
    elif error:
        flash = f"Correction failed: {error}"
        flash_error = True

    return templates.TemplateResponse(
        request,
        "meeting.html",
        {
            "data": data,
            "tasks": with_overdue_flags(data.tasks),
            "flash": flash,
            "flash_error": flash_error,
        },
    )


@router.post("/meetings/{meeting_id}/correct")
async def submit_correction(
    meeting_id: str,
    text: str = Form(default=""),
    audio: Optional[UploadFile] = File(default=None),
):
    transcript = text.strip()
    audio_path = None

    if audio is not None and audio.filename:
        from pathlib import Path
        import tempfile

        from app.transcription.whisper_client import transcribe

        suffix = Path(audio.filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await audio.read())
            audio_path = tmp.name
        transcribed = transcribe(audio_path)
        transcript = (transcript + "\n" + transcribed).strip() if transcript else transcribed

    if not transcript:
        return RedirectResponse(f"/meetings/{meeting_id}?error={quote('No text or audio provided')}", status_code=303)

    ambiguous: list[str] = []

    def _on_resolved(entry) -> None:
        if entry.outcome == "ambiguous_created":
            ambiguous.append(f"{entry.name} (possible duplicate of {entry.possible_duplicate_of})")

    conn = get_connection()
    try:
        # interactive=False: this is a web request, not a terminal - the
        # confirm-queue reads from stdin and would hang forever here. See
        # resolve_entity()'s docstring.
        append_correction(
            conn, meeting_id, transcript, audio_path=audio_path, interactive=False, on_resolved=_on_resolved
        )
    except Exception as exc:
        return RedirectResponse(f"/meetings/{meeting_id}?error={quote(str(exc)[:200])}", status_code=303)
    finally:
        conn.close()

    redirect_url = f"/meetings/{meeting_id}?corrected=1"
    if ambiguous:
        redirect_url += f"&flagged={quote('; '.join(ambiguous))}"
    return RedirectResponse(redirect_url, status_code=303)
