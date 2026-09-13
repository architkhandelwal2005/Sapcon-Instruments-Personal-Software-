"""The WhatsApp intake webhook: a voice note or typed note becomes a new meeting
(the same pipeline /meetings/new already calls); a photo becomes a card/diary
capture; a message starting with "ask" is a lookup, not something to log.

Security: every request must carry a valid Twilio signature (the only thing
standing between the public internet and writing rows into the CRM) AND come from
a phone number in whatsapp_senders - an unknown number is silently ignored, no
reply, so it never confirms the number is being watched.

Twilio expects a fast webhook ack; the actual work (transcription, extraction,
verification, resolution) runs in a background task after the response is sent.
"""

import os
import tempfile
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from twilio.request_validator import RequestValidator

from app.capture.pipeline import ingest_capture
from app.db import get_connection
from app.ingestion.pipeline import ingest_new_meeting
from app.llm import transcribe_audio
from app.query import ask as run_ask
from app.whatsapp.client import download_media, send_whatsapp
from app.whatsapp.reply import ask_reply, capture_reply, meeting_reply

router = APIRouter()

_AUDIO_EXT = {
    "audio/ogg": ".ogg", "audio/opus": ".ogg", "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a", "audio/amr": ".amr", "audio/wav": ".wav",
}


def _base_url() -> str:
    return os.environ["PUBLIC_BASE_URL"].rstrip("/")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form = dict(await request.form())
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    url = _base_url() + request.url.path
    if not validator.validate(url, form, signature):
        raise HTTPException(status_code=400, detail="Invalid Twilio signature")

    background_tasks.add_task(
        _process_message,
        from_=form.get("From", ""),
        body=form.get("Body", ""),
        num_media=int(form.get("NumMedia", "0") or "0"),
        media_url=form.get("MediaUrl0"),
        media_type=form.get("MediaContentType0"),
    )
    # Empty TwiML - we reply asynchronously via the REST API once work finishes,
    # not through this webhook response.
    return PlainTextResponse('<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="text/xml")


def _lookup_sender(conn, from_: str) -> Optional[str]:
    phone = from_.removeprefix("whatsapp:")
    with conn.cursor() as cur:
        cur.execute("select entity_id from whatsapp_senders where phone = %s", (phone,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _process_message(*, from_: str, body: str, num_media: int, media_url: Optional[str], media_type: Optional[str]) -> None:
    conn = get_connection()
    try:
        logged_by = _lookup_sender(conn, from_)
        if logged_by is None:
            return  # not on the allowlist - silently ignore
        try:
            _dispatch(conn, from_, body, num_media, media_url, media_type, logged_by)
        except Exception:
            send_whatsapp(from_, "Got your message but couldn't process it - will follow up.")
            raise
    finally:
        conn.close()


def _dispatch(conn, from_, body, num_media, media_url, media_type, logged_by) -> None:
    base = _base_url()

    if num_media > 0 and media_type and media_url:
        if media_type.startswith("audio/"):
            _handle_audio(conn, from_, media_url, media_type, logged_by, base)
            return
        if media_type.startswith("image/"):
            _handle_photo(conn, from_, body, media_url, media_type, logged_by, base)
            return
        send_whatsapp(from_, "That attachment type isn't supported yet - send a voice note, a photo, or text.")
        return

    text = (body or "").strip()
    if not text:
        return
    if text.lower().startswith("ask"):
        question = text[3:].strip(" :").strip()
        _handle_ask(conn, from_, question)
        return
    _handle_text_meeting(conn, from_, text, logged_by, base)


def _handle_audio(conn, from_, media_url, media_type, logged_by, base) -> None:
    audio_bytes = download_media(media_url)
    suffix = _AUDIO_EXT.get(media_type, ".ogg")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        audio_path = tmp.name
    transcript = transcribe_audio(audio_bytes, media_type)
    if not transcript.strip():
        send_whatsapp(from_, "Got the voice note but couldn't make out any speech - try again?")
        return
    result = ingest_new_meeting(conn, transcript, date.today(), audio_path=audio_path, logged_by=logged_by)
    send_whatsapp(from_, meeting_reply(result, f"{base}/meetings/{result.meeting_id}"))


def _handle_text_meeting(conn, from_, text, logged_by, base) -> None:
    result = ingest_new_meeting(conn, text, date.today(), logged_by=logged_by)
    send_whatsapp(from_, meeting_reply(result, f"{base}/meetings/{result.meeting_id}"))


def _handle_photo(conn, from_, caption, media_url, media_type, logged_by, base) -> None:
    image_bytes = download_media(media_url)
    # Caption convention: "diary" anywhere in the caption -> diary page,
    # otherwise card sheet (the more common, ongoing habit).
    capture_type = "diary" if "diary" in (caption or "").lower() else "card"
    result = ingest_capture(conn, image_bytes, media_type, capture_type, date.today(), logged_by=logged_by)
    send_whatsapp(from_, capture_reply(result, capture_type, f"{base}/review/capture/{result.capture_event_id}"))


def _handle_ask(conn, from_, question) -> None:
    if not question:
        send_whatsapp(from_, "Ask me something, e.g. \"ask brief me on Priya Nair\".")
        return
    result = run_ask(conn, question)
    send_whatsapp(from_, ask_reply(result))
