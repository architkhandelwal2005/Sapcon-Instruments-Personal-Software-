"""The WhatsApp intake webhook (Meta Cloud API): a voice note or typed note
becomes a new meeting (the same pipeline /meetings/new already calls); a photo
becomes a card/diary capture; a message starting with "ask" is a lookup, not
something to log.

Security: every POST must carry a valid X-Hub-Signature-256 over the exact raw
body (the only thing standing between the public internet and writing rows into
the CRM) AND come from a phone number in whatsapp_senders - an unknown number is
silently ignored, no reply, so it never confirms the number is being watched.

Meta expects a fast 200 on the webhook; the actual work (transcription,
extraction, verification, resolution) runs in a background task after the
response is sent.
"""

import os
import re
import tempfile
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.capture.pipeline import ingest_capture
from app.db import get_connection, release_connection
from app.ingestion.pipeline import ingest_new_meeting
from app.llm import transcribe_audio
from app.query import ask as run_ask
from app.whatsapp.client import download_media, send_whatsapp, valid_signature
from app.whatsapp.reply import ask_reply, capture_reply, failure_reply, meeting_reply

router = APIRouter()

_AUDIO_EXT = {
    "audio/ogg": ".ogg", "audio/opus": ".ogg", "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a", "audio/amr": ".amr", "audio/wav": ".wav",
}


def _base_url() -> str:
    return os.environ["PUBLIC_BASE_URL"].rstrip("/")


@router.get("/whatsapp/webhook")
def verify_webhook(request: Request):
    """Meta's one-time subscription handshake: echo hub.challenge back when the
    token matches the one configured in the app dashboard."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    if not valid_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    for message in _messages(payload):
        background_tasks.add_task(_process_message, message=message)
    # Always a plain 200: Meta retries anything else, and a delivery-status
    # callback (no messages at all) is a normal, ignorable payload.
    return Response(status_code=200)


def _messages(payload: dict) -> list[dict]:
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            out.extend((change.get("value") or {}).get("messages") or [])
    return out


def _lookup_sender(conn, wa_id: str) -> Optional[str]:
    """wa_id is digits only ("919893351932"); stored numbers are E.164
    ("+919893351932"), so match on digits."""
    digits = re.sub(r"\D", "", wa_id or "")
    if not digits:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "select entity_id from whatsapp_senders "
            "where regexp_replace(phone, '\\D', '', 'g') = %s",
            (digits,),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _process_message(*, message: dict) -> None:
    from_ = message.get("from", "")
    conn = get_connection()
    try:
        logged_by = _lookup_sender(conn, from_)
        if logged_by is None:
            return  # not on the allowlist - silently ignore
        try:
            _dispatch(conn, from_, message, logged_by)
        except Exception as exc:
            # Anything that logs a note persists it to ingestion_failures before
            # re-raising, so it can be retried; a lookup has nothing to keep.
            saved = _is_lookup(message) is False
            send_whatsapp(from_, failure_reply(exc, saved=saved))
            raise
    finally:
        release_connection(conn)


def _is_lookup(message: dict) -> bool:
    """A message starting with "ask" is a question, not something to log."""
    if message.get("type") != "text":
        return False
    return ((message.get("text") or {}).get("body") or "").strip().lower().startswith("ask")


def _dispatch(conn, from_, message: dict, logged_by) -> None:
    base = _base_url()
    kind = message.get("type")

    if kind == "audio":
        _handle_audio(conn, from_, (message.get("audio") or {}).get("id"), logged_by, base)
        return
    if kind == "image":
        image = message.get("image") or {}
        _handle_photo(conn, from_, image.get("caption"), image.get("id"), logged_by, base)
        return
    if kind != "text":
        send_whatsapp(from_, "That message type isn't supported yet - send a voice note, a photo, or text.")
        return

    text = ((message.get("text") or {}).get("body") or "").strip()
    if not text:
        return
    if _is_lookup(message):
        _handle_ask(conn, from_, text[3:].strip(" :").strip())
        return
    _handle_text_meeting(conn, from_, text, logged_by, base)


def _handle_audio(conn, from_, media_id, logged_by, base) -> None:
    audio_bytes, mime_type = download_media(media_id)
    suffix = _AUDIO_EXT.get(mime_type, ".ogg")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        audio_path = tmp.name
    transcript = transcribe_audio(audio_bytes, mime_type)
    if not transcript.strip():
        send_whatsapp(from_, "Got the voice note but couldn't make out any speech - try again?")
        return
    result = ingest_new_meeting(conn, transcript, date.today(), audio_path=audio_path, logged_by=logged_by)
    send_whatsapp(from_, meeting_reply(result, f"{base}/meetings/{result.meeting_id}"))


def _handle_text_meeting(conn, from_, text, logged_by, base) -> None:
    result = ingest_new_meeting(conn, text, date.today(), logged_by=logged_by)
    send_whatsapp(from_, meeting_reply(result, f"{base}/meetings/{result.meeting_id}"))


def _handle_photo(conn, from_, caption, media_id, logged_by, base) -> None:
    image_bytes, mime_type = download_media(media_id)
    # Caption convention: "diary" anywhere in the caption -> diary page,
    # otherwise card sheet (the more common, ongoing habit).
    capture_type = "diary" if "diary" in (caption or "").lower() else "card"
    result = ingest_capture(conn, image_bytes, mime_type, capture_type, date.today(), logged_by=logged_by)
    send_whatsapp(from_, capture_reply(result, capture_type, f"{base}/review/capture/{result.capture_event_id}"))


def _handle_ask(conn, from_, question) -> None:
    if not question:
        send_whatsapp(from_, "Ask me something, e.g. \"ask brief me on Priya Nair\".")
        return
    result = run_ask(conn, question)
    send_whatsapp(from_, ask_reply(result))
