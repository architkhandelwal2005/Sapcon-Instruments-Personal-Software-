"""Web upload of a card/diary photo - the fallback used to prove the capture
pipeline works before WhatsApp photo intake exists. WhatsApp will call
app.capture.pipeline.ingest_capture directly with the same signature.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.capture.pipeline import ingest_capture
from app.db import get_connection, release_connection

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/captures/new", response_class=HTMLResponse)
def new_capture_form(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        request, "capture_new.html", {"today": date.today().isoformat(), "error": error}
    )


@router.post("/captures/new")
async def create_capture(
    capture_type: str = Form(...),
    captured_date: str = Form(...),
    photo: UploadFile = File(...),
):
    if capture_type not in ("card", "diary"):
        return RedirectResponse(f"/captures/new?error={quote('Pick card or diary')}", status_code=303)
    try:
        cdate = datetime.strptime(captured_date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(f"/captures/new?error={quote('Enter the date as YYYY-MM-DD')}", status_code=303)

    image_bytes = await photo.read()
    if not image_bytes:
        return RedirectResponse(f"/captures/new?error={quote('No photo uploaded')}", status_code=303)
    mime_type = photo.content_type or "image/jpeg"

    conn = get_connection()
    try:
        result = ingest_capture(conn, image_bytes, mime_type, capture_type, cdate)
    except Exception as exc:
        return RedirectResponse(f"/captures/new?error={quote(str(exc)[:200])}", status_code=303)
    finally:
        release_connection(conn)

    return RedirectResponse(f"/review/capture/{result.capture_event_id}", status_code=303)
