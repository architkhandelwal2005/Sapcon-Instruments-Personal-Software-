"""The WhatsApp intake webhook (Meta Cloud API).

Everything that arrives as words - typed, or spoken and transcribed - goes to
the planner, which reads the conversation so far and says what the message
wants: record it, answer it, change something, undo, or just talk. There are no
keywords to remember. This replaced a ladder of prefix and regex checks that
could recognise three instructions and turned everything else, including
"hello", into a meeting.

A photo is still a card/diary capture, decided by its caption.

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
import sys
from datetime import date
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.capture.pipeline import ingest_capture
from app.capture.storage import upload_audio
from app.db import get_connection, release_connection
from app.ingestion.failures import record_failure
from app.ingestion.pipeline import append_correction, ingest_new_meeting
from app.llm import transcribe_audio
from app.transcription.vocabulary import known_names
from app.phone import DEFAULT_CC, normalize_phone
from app.query import ask as run_ask
from app.whatsapp.client import download_media, send_whatsapp, valid_signature
from app.whatsapp.delivery import record_sent, record_status, statuses
from app.commands import ParsedCommand
from app.whatsapp.commands import (
    apply_choice,
    apply_command,
    choice_payload,
    command_reply,
    is_undo,
    parse_choice,
    pending_for,
    remember,
    undo_command,
)
from app.agent import Plan, plan_message, recent, remember_turn, render
from app.minutes.generate import fetch_meeting_minutes_data
from app.whatsapp.readback import meeting_readback_reply
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
    if not _messages(payload):
        background_tasks.add_task(_record_statuses, payload=payload)
    # Always a plain 200: Meta retries anything else.
    return Response(status_code=200)


def _record_statuses(*, payload: dict) -> None:
    """Delivery outcomes for messages we sent. Meta's answer to a send only
    says it was accepted; this is where "it actually arrived" comes from, and
    where a message it silently dropped stops being invisible."""
    rows = statuses(payload)
    if not rows:
        return
    conn = get_connection()
    try:
        for status in rows:
            record_status(conn, status)
    finally:
        release_connection(conn)


def _messages(payload: dict) -> list[dict]:
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            out.extend((change.get("value") or {}).get("messages") or [])
    return out


def _lookup_sender(conn, wa_id: str) -> Optional[str]:
    """wa_id is digits only ("919893351932") while a stored number is written
    however it was entered, so both sides go through the same normalisation.
    The bare national number is accepted too, since a row saved as
    "9893351932" means the same phone."""
    try:
        digits = normalize_phone(wa_id)
    except ValueError:
        return None
    national = digits[len(DEFAULT_CC):] if digits.startswith(DEFAULT_CC) else digits
    with conn.cursor() as cur:
        cur.execute(
            r"select entity_id from whatsapp_senders "
            r"where regexp_replace(phone, '\D', '', 'g') in (%s, %s)",
            (digits, national),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _say(conn, to: str, body: str) -> Optional[str]:
    """Send a reply and remember that we did, so a message Meta later drops is
    visible instead of silently missing. Returns the outbound message id."""
    wa_message_id = send_whatsapp(to, body)
    record_sent(conn, wa_message_id, to)
    remember_turn(conn, to, "us", body)
    return wa_message_id


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
            # The note paths persist to ingestion_failures before re-raising and
            # mark the exception as such; a lookup has nothing to keep, and the
            # reply must not claim otherwise.
            _say(conn, from_, failure_reply(exc, saved=getattr(exc, "note_was_saved", False)))
            raise
    finally:
        release_connection(conn)


def _reply_to(message: dict) -> Optional[str]:
    """The id of the message this one replies to, when Meta reports one."""
    return (message.get("context") or {}).get("id")


def _dispatch(conn, from_, message: dict, logged_by) -> None:
    base = _base_url()
    kind = message.get("type")
    reply_to = _reply_to(message)

    if kind == "audio":
        _handle_audio(conn, from_, (message.get("audio") or {}).get("id"), logged_by, base,
                      reply_to=reply_to)
        return
    if kind == "image":
        image = message.get("image") or {}
        _handle_photo(conn, from_, image.get("caption"), image.get("id"), logged_by, base)
        return
    if kind != "text":
        _say(conn, from_, "That message type isn't supported yet - send a voice note, a photo, or text.")
        return

    text = ((message.get("text") or {}).get("body") or "").strip()
    if not text:
        return
    _route_words(conn, from_, text, logged_by, base, audio_path=None, reply_to=reply_to)


def _route_words(conn, from_, text: str, logged_by, base, *, audio_path, reply_to: Optional[str]) -> None:
    """One route for anything that arrives as words, typed or spoken.

    Two things are decided before the model is asked anything, because in both
    cases the reply he is answering already says what he means, and a model
    that disagreed would lose the message: a reply to a readback is a
    correction to that meeting, and a reply to a question we asked is the
    answer to it. Everything else goes to the planner, which reads the
    conversation so far rather than this message alone."""
    remember_turn(conn, from_, "them", text)

    meeting_id = _correction_target(conn, reply_to)
    if meeting_id is not None:
        _apply_correction(conn, from_, text, meeting_id, logged_by, base, audio_path=audio_path)
        return
    if _handle_reply_to_pending(conn, from_, text, base, reply_to):
        return

    plan = plan_message(text, render(recent(conn, from_)))
    _carry_out(conn, from_, plan, text, logged_by, base, audio_path=audio_path)


def _carry_out(conn, from_, plan: Plan, text: str, logged_by, base, *, audio_path) -> None:
    """Do what the plan says. The model chose the intent and the words; which
    row those words mean is still decided in SQL, so an instruction that
    matches two tasks changes neither."""
    if plan.action == "chat":
        # Nothing to record and nothing to look up. A greeting used to run the
        # whole pipeline over one word and leave an error row behind.
        if plan.reply:
            _say(conn, from_, plan.reply)
        return

    if plan.action == "ask":
        _handle_ask(conn, from_, plan.question or text)
        return

    if plan.action == "undo":
        _handle_undo(conn, from_, base)
        return

    if plan.action in ("assign_task", "complete_task", "drop_lead"):
        command = ParsedCommand(action=plan.action, target=plan.target,
                                person=plan.person or None)
        outcome = apply_command(conn, command)
        if outcome.status == "not_found":
            # He may be recording something new rather than pointing at a row
            # that exists. Filing it keeps the note; guessing a row would not.
            _log_note(conn, from_, text, logged_by, base, audio_path=audio_path)
            return
        _send_command_outcome(conn, from_, outcome, base, command=command)
        return

    _log_note(conn, from_, text, logged_by, base, audio_path=audio_path)


def _log_note(conn, from_, text, logged_by, base, *, audio_path) -> None:
    try:
        result = ingest_new_meeting(conn, text, date.today(), audio_path=audio_path, logged_by=logged_by)
    except Exception as exc:
        exc.note_was_saved = True  # ingest_new_meeting recorded it for a retry
        raise
    _send_readback(conn, from_, result, base)


UNDO_WINDOW_HOURS = 12


def _handle_undo(conn, from_, base) -> None:
    """"undo" said on its own, rather than as a reply to the change itself.

    Only a recent change, and only once. An undo means "that thing you just
    did"; reaching back further would let the word, typed out of context,
    silently reverse something nobody was thinking about. Undoing an older
    change is a job for the website, where you can see what you are changing
    before you change it."""
    with conn.cursor() as cur:
        cur.execute(
            "select wa_message_id, payload from whatsapp_pending "
            "where sender_phone = %s and kind = 'undo' and used_at is null "
            "  and created_at > now() - make_interval(hours => %s) "
            "order by created_at desc limit 1",
            (from_, UNDO_WINDOW_HOURS),
        )
        row = cur.fetchone()
    conn.rollback()
    if row is None:
        _say(conn, from_, "Nothing recent of mine to undo. If you need an older change "
                          f"reversed, it is on {base}/tasks.")
        return
    outcome = undo_command(conn, row[1]["token"])
    with conn.cursor() as cur:
        cur.execute("update whatsapp_pending set used_at = now() where wa_message_id = %s",
                    (row[0],))
    conn.commit()
    _say(conn, from_, command_reply(outcome, base))


def _handle_reply_to_pending(conn, from_, text: str, base, reply_to: Optional[str]) -> bool:
    """A reply to something the bot is waiting on: a number picking one of the
    tasks it offered, or "undo" on a change it just made. Returns whether this
    message was one of those."""
    pending = pending_for(conn, reply_to)
    if pending is None:
        return False

    if pending["kind"] == "undo" and is_undo(text):
        outcome = undo_command(conn, pending["payload"]["token"])
        with conn.cursor() as cur:
            # Spent, so replying "undo" to the same message twice cannot put a
            # row back to a state it has since been moved on from.
            cur.execute("update whatsapp_pending set used_at = now() where wa_message_id = %s",
                        (reply_to,))
        conn.commit()
        _say(conn, from_, command_reply(outcome, base))
        return True

    if pending["kind"] == "choice":
        candidates = pending["payload"]["candidates"]
        index = parse_choice(text, len(candidates))
        if index is None:
            return False  # not a number - treat it as a fresh message
        outcome = apply_choice(conn, pending["payload"], index)
        _send_command_outcome(conn, from_, outcome, base)
        return True
    return False


def _send_command_outcome(conn, from_, outcome, base, *, command=None) -> None:
    """Send the result, and remember what the reply to it would mean - a number
    when choices were offered, "undo" when something changed."""
    wa_message_id = _say(conn, from_, command_reply(outcome, base))
    if not wa_message_id:
        return
    if outcome.status == "ambiguous" and command is not None:
        remember(conn, wa_message_id, from_, "choice", choice_payload(command, outcome))
    elif outcome.status == "applied" and outcome.undo_token:
        remember(conn, wa_message_id, from_, "undo", {"token": outcome.undo_token})


def _apply_correction(conn, from_, text, meeting_id, logged_by, base, *, audio_path) -> None:
    try:
        result = append_correction(conn, meeting_id, text, audio_path=audio_path)
    except Exception as exc:
        exc.note_was_saved = True
        raise
    _send_readback(conn, from_, result, base)


def _correction_target(conn, reply_to: Optional[str]) -> Optional[str]:
    """The meeting a readback belongs to, when this message replies to one.

    Deliberately no "most recent meeting" fallback: he records between
    appointments, so a time-window guess would attach a correction to the wrong
    meeting and nothing would ever surface it."""
    if not reply_to:
        return None
    with conn.cursor() as cur:
        cur.execute("select meeting_id from whatsapp_threads where wa_message_id = %s", (reply_to,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _send_readback(conn, from_, result, base) -> None:
    """The readback is worth a lot but is not worth losing a meeting over: the
    note is already committed by here, so any failure falls back to counts."""
    url = f"{base}/meetings/{result.meeting_id}"
    try:
        data = fetch_meeting_minutes_data(conn, result.meeting_id)
        body = meeting_readback_reply(data, result.resolutions, url)
    except Exception:
        body = meeting_reply(result, url)
    wa_message_id = _say(conn, from_, body)
    if wa_message_id:
        _remember_thread(conn, wa_message_id, result.meeting_id, from_)


def _remember_thread(conn, wa_message_id: str, meeting_id: str, from_: str) -> None:
    """So a reply to this readback can be routed back to its meeting."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into whatsapp_threads (wa_message_id, meeting_id, sender_entity_id) "
                "values (%s, %s, (select entity_id from whatsapp_senders "
                r"                 where regexp_replace(phone, '\D', '', 'g') = %s)) "
                "on conflict (wa_message_id) do nothing",
                (wa_message_id, meeting_id, re.sub(r"\D", "", from_ or "")),
            )
        conn.commit()
    except Exception:
        conn.rollback()  # a lost thread row costs reply-routing, never the meeting


def _handle_audio(conn, from_, media_id, logged_by, base, *, reply_to: Optional[str]) -> None:
    """A voice note takes about a minute to come back - download, transcribe,
    extract, verify, resolve - and on a sleeping free instance rather longer.
    A minute of silence reads as a dead number, so say we have it first.

    The recording is kept before a word of it is read. It used to go to a temp
    file on a host whose disk is wiped on every restart, and transcription ran
    before anything at all was recorded - so when the model refused, and it did
    refuse a real 1:23 note, there was no row, no retry and no trace that the
    note had ever existed. Now the refusal costs a wait instead of the note."""
    _say(conn, from_, "Got your voice note - listening to it now.")
    audio_bytes, mime_type = download_media(media_id)
    audio_url = _keep_audio(audio_bytes, mime_type)

    try:
        transcript = transcribe_audio(audio_bytes, mime_type, known_names(conn))
    except Exception as exc:
        record_failure(conn, date.today(), audio_url, None, exc)
        exc.note_was_saved = bool(audio_url)
        raise
    if not transcript.strip():
        _say(conn, from_, "Got the voice note but couldn't make out any speech - try again?")
        return
    _route_words(conn, from_, transcript, logged_by, base, audio_path=audio_url, reply_to=reply_to)


def _keep_audio(audio_bytes: bytes, mime_type: str) -> Optional[str]:
    """Put the recording somewhere that outlives this container, and say where.

    Returns None if storage itself is unreachable - the note then goes on to
    transcription anyway, because a storage outage is no reason to refuse a
    voice note that might transcribe perfectly well."""
    try:
        name = f"{uuid4()}{_AUDIO_EXT.get(mime_type, '.ogg')}"
        return upload_audio(audio_bytes, mime_type, name)
    except Exception as exc:
        print(f"could not store the voice note: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _handle_photo(conn, from_, caption, media_id, logged_by, base) -> None:
    _say(conn, from_, "Got the photo - reading it now.")
    image_bytes, mime_type = download_media(media_id)
    # Caption convention: "diary" anywhere in the caption -> diary page,
    # otherwise card sheet (the more common, ongoing habit).
    capture_type = "diary" if "diary" in (caption or "").lower() else "card"
    result = ingest_capture(conn, image_bytes, mime_type, capture_type, date.today(), logged_by=logged_by)
    _say(conn, from_, capture_reply(result, capture_type, f"{base}/review/capture/{result.capture_event_id}"))


def _handle_ask(conn, from_, question) -> None:
    if not question:
        _say(conn, from_, "Ask me something, e.g. \"ask brief me on Priya Nair\".")
        return
    result = run_ask(conn, question)
    _say(conn, from_, ask_reply(result))
