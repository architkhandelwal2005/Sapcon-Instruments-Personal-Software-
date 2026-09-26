from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.ingestion.pipeline import append_correction
from app.minutes.generate import fetch_meeting_minutes_data, generate_readback
from app.web.helpers import save_and_transcribe, with_overdue_flags
from app.web.templating import templates

router = APIRouter()


@router.get("/meetings", response_class=HTMLResponse)
def meetings_log(request: Request, kind: Optional[str] = None):
    """Every meeting, newest first - customer field visits and internal office
    meetings side by side, filterable by kind."""
    where, params = "", {}
    if kind in ("field_visit", "internal"):
        where, params = "where m.kind = %(kind)s", {"kind": kind}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select m.id, m.meeting_date, m.kind, pc.canonical_name, m.summary, m.review_status,
                       (select count(*) from decisions d where d.meeting_id = m.id and d.review_status <> 'rejected'),
                       (select count(*) from tasks t where t.meeting_id = m.id
                          and t.review_status <> 'rejected' and t.status = 'open')
                from meetings m
                left join entities pc on pc.id = m.primary_contact_id
                {where}
                order by m.meeting_date desc, m.created_at desc
                limit 300
                """,
                params,
            )
            rows = [
                {
                    "id": str(mid), "meeting_date": mdate, "kind": mkind, "primary_contact_name": pc,
                    "summary": summary, "review_status": rs, "decision_count": dc, "open_tasks": ot,
                }
                for mid, mdate, mkind, pc, summary, rs, dc, ot in cur.fetchall()
            ]
    finally:
        release_connection(conn)
    return templates.TemplateResponse(request, "meetings_log.html", {"rows": rows, "active_kind": kind or ""})


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
        release_connection(conn)

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


@router.get("/meetings/{meeting_id}/readback", response_class=PlainTextResponse)
def meeting_readback(meeting_id: str):
    """The 'here's what I understood' plain-text recap - select-all, paste into
    a message. Same formatter the CLI prints."""
    conn = get_connection()
    try:
        return generate_readback(conn, meeting_id)
    finally:
        release_connection(conn)


@router.post("/meetings/{meeting_id}/correct")
async def submit_correction(
    meeting_id: str,
    text: str = Form(default=""),
    audio: Optional[UploadFile] = File(default=None),
):
    transcript = text.strip()
    audio_path = None

    if audio is not None and audio.filename:
        transcribed, audio_path = await save_and_transcribe(audio)
        transcript = (transcript + "\n" + transcribed).strip() if transcript else transcribed

    if not transcript:
        return RedirectResponse(f"/meetings/{meeting_id}?error={quote('No text or audio provided')}", status_code=303)

    ambiguous: list[str] = []

    def _on_resolved(mentioned: str, r) -> None:
        if r.outcome == "uncertain_created":
            ambiguous.append(f"{mentioned} (possible duplicate of {r.possible_duplicate_of})")

    conn = get_connection()
    try:
        append_correction(conn, meeting_id, transcript, audio_path=audio_path, on_resolved=_on_resolved)
    except Exception as exc:
        return RedirectResponse(f"/meetings/{meeting_id}?error={quote(str(exc)[:200])}", status_code=303)
    finally:
        release_connection(conn)

    redirect_url = f"/meetings/{meeting_id}?corrected=1"
    if ambiguous:
        redirect_url += f"&flagged={quote('; '.join(ambiguous))}"
    return RedirectResponse(redirect_url, status_code=303)
