"""Shared ingestion pipeline: transcript -> extract + verify -> LLM entity
resolution -> write meeting/connections/tasks, each row carrying a confidence
and a review_status. High-confidence, transcript-verified items are
auto_confirmed (live, spot-checkable); everything else is pending until the
office boy clears it in the review UI.

Used by both the CLI (scripts/ingest_audio.py) and the web app.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import psycopg

from app.entity_resolution.employees import employee_roster, match_employee
from app.entity_resolution.resolve import ResolutionResult, resolve_entity
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.failures import record_failure
from app.review import finalise_meeting_status


@dataclass
class IngestResult:
    meeting_id: str
    entity_count: int
    connection_count: int
    task_count: int
    auto_confirmed: int
    pending: int
    resolutions: list[ResolutionResult] = field(default_factory=list)
    decision_count: int = 0
    kind: str = "field_visit"


OnResolved = Optional[Callable[[str, ResolutionResult], None]]


def _row_status(confidence: Optional[str]) -> str:
    return "auto_confirmed" if confidence == "high" else "pending"


def _resolve_entities(conn, entities, transcript, on_resolved: OnResolved) -> dict:
    """extracted name -> ResolutionResult"""
    resolved: dict[str, ResolutionResult] = {}
    for e in entities:
        r = resolve_entity(
            conn, e.name, e.entity_type, transcript,
            extraction_confidence=e.confidence,
            attrs={"title": e.title, "phone": e.phone, "email": e.email, "region": e.region},
        )
        resolved[e.name] = r
        if on_resolved:
            on_resolved(e.name, r)
    return resolved


def _resolve_ref(conn, resolved: dict, name: str, transcript: str, on_resolved: OnResolved, fallback: str = "company") -> str:
    """A connection/task referenced a name; return its entity_id, resolving on
    the fly if the extraction didn't list it as an entity."""
    if name in resolved:
        return resolved[name].entity_id
    r = resolve_entity(conn, name, fallback, transcript, extraction_confidence="low")
    resolved[name] = r
    if on_resolved:
        on_resolved(name, r)
    return r.entity_id


def _write_attendees(conn, meeting_id, names: list[str]) -> None:
    """Each attendee kept as heard; linked to an employee only on a confident
    match. A correction re-listing someone already recorded adds nothing."""
    with conn.cursor() as cur:
        cur.execute("select lower(name), employee_id from meeting_attendees where meeting_id = %s", (meeting_id,))
        existing = cur.fetchall()
        seen_names = {n for n, _ in existing}
        seen_ids = {e for _, e in existing if e}
        for name in names:
            name = name.strip()
            if not name or name.lower() in seen_names:
                continue
            emp = match_employee(conn, name)
            if emp and emp in seen_ids:
                continue
            cur.execute(
                "insert into meeting_attendees (meeting_id, name, employee_id) values (%s,%s,%s)",
                (meeting_id, name, emp),
            )
            seen_names.add(name.lower())
            if emp:
                seen_ids.add(emp)


def _write_meeting_body(conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript) -> tuple[int, int, int, int, int]:
    conn_count = auto = pending = 0
    seen: set = set()
    _write_attendees(conn, meeting_id, result.attendees)
    with conn.cursor() as cur:
        for c in result.connections:
            sid = _resolve_ref(conn, resolved, c.source, transcript, on_resolved)
            tid = _resolve_ref(conn, resolved, c.target, transcript, on_resolved)
            key = (sid, c.suggested_role, tid)
            if key in seen:
                continue
            seen.add(key)
            status = _row_status(c.confidence)
            cur.execute(
                "insert into relations (source_id, target_id, role_tag, meeting_id, provenance, recorded_at, "
                "description, source_quote, confidence, review_status) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (sid, tid, c.suggested_role, meeting_id, c.provenance, meeting_date,
                 c.description, c.source_quote, c.confidence, status),
            )
            conn_count += 1
            auto, pending = (auto + 1, pending) if status == "auto_confirmed" else (auto, pending + 1)

    decision_count = 0
    with conn.cursor() as cur:
        for d in result.decisions:
            status = _row_status(d.confidence)
            cur.execute(
                "insert into decisions (meeting_id, description, source_quote, confidence, review_status) "
                "values (%s,%s,%s,%s,%s)",
                (meeting_id, d.description, d.source_quote, d.confidence, status),
            )
            decision_count += 1
            auto, pending = (auto + 1, pending) if status == "auto_confirmed" else (auto, pending + 1)

    task_count = 0
    with conn.cursor() as cur:
        for t in result.tasks:
            rel_id = _resolve_ref(conn, resolved, t.target_entity, transcript, on_resolved) if t.target_entity else None
            due = resolve_due_date(meeting_date, t.relative_due)
            status = _row_status(t.confidence)
            cur.execute(
                "insert into tasks (description, related_entity_id, meeting_id, due_date, "
                "confidence, source_quote, review_status) values (%s,%s,%s,%s,%s,%s,%s) returning id",
                (t.description, rel_id, meeting_id, due, t.confidence, t.source_quote, status),
            )
            (task_id,) = cur.fetchone()
            for name in dict.fromkeys(n.strip() for n in t.assignees if n.strip()):
                cur.execute(
                    "insert into task_assignees (task_id, name, employee_id) values (%s,%s,%s)",
                    (task_id, name, match_employee(conn, name)),
                )
            task_count += 1
            auto, pending = (auto + 1, pending) if status == "auto_confirmed" else (auto, pending + 1)

    return conn_count, task_count, decision_count, auto, pending


def ingest_new_meeting(
    conn: psycopg.Connection,
    transcript: str,
    meeting_date: date,
    primary_contact_name: Optional[str] = None,
    location: Optional[str] = None,
    audio_path: Optional[str] = None,
    on_resolved: OnResolved = None,
    logged_by: Optional[str] = None,
) -> IngestResult:
    """logged_by: entity id of whoever recorded this interaction (the uncle, office
    boy, or a marketing employee) - null when the concept doesn't apply (e.g. CLI
    testing). Lets a lead's activity history be filtered to one employee's calls."""
    try:
        result = extract(transcript, employee_roster(conn))
        resolved = _resolve_entities(conn, result.entities, transcript, on_resolved)

        primary_id = None
        if primary_contact_name:
            primary_id = _resolve_ref(conn, resolved, primary_contact_name, transcript, on_resolved, fallback="person")

        with conn.cursor() as cur:
            cur.execute(
                "insert into meetings (meeting_date, primary_contact_id, location, raw_transcript, audio_url, "
                "summary, logged_by, kind) values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                (meeting_date, primary_id, location, transcript, audio_path, result.summary, logged_by, result.kind),
            )
            (meeting_id,) = cur.fetchone()

        cc, tc, dc, auto, pending = _write_meeting_body(
            conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript
        )
        finalise_meeting_status(conn, meeting_id)
        conn.commit()
        return IngestResult(
            str(meeting_id), len(resolved), cc, tc, auto, pending, list(resolved.values()),
            decision_count=dc, kind=result.kind,
        )
    except Exception as exc:
        conn.rollback()
        record_failure(conn, meeting_date, audio_path, transcript, exc)
        raise


def append_correction(
    conn: psycopg.Connection,
    meeting_id: str,
    transcript: str,
    audio_path: Optional[str] = None,
    on_resolved: OnResolved = None,
) -> IngestResult:
    meeting_date = None
    try:
        with conn.cursor() as cur:
            cur.execute("select meeting_date from meetings where id = %s", (meeting_id,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No meeting {meeting_id!r}")
            meeting_date = row[0]
            cur.execute(
                "update meetings set raw_transcript = raw_transcript || %s where id = %s",
                (f"\n\n--- Correction (appended {date.today().isoformat()}) ---\n\n{transcript}", meeting_id),
            )

        result = extract(transcript, employee_roster(conn))
        resolved = _resolve_entities(conn, result.entities, transcript, on_resolved)
        cc, tc, dc, auto, pending = _write_meeting_body(
            conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript
        )
        finalise_meeting_status(conn, meeting_id)
        conn.commit()
        return IngestResult(
            str(meeting_id), len(resolved), cc, tc, auto, pending, list(resolved.values()),
            decision_count=dc,
        )
    except Exception as exc:
        conn.rollback()
        record_failure(conn, meeting_date or date.today(), audio_path, transcript, exc)
        raise
