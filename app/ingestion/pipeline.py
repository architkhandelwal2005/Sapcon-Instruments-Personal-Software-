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

from app.entity_resolution.resolve import ResolutionResult, resolve_entity
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.failures import record_failure


@dataclass
class IngestResult:
    meeting_id: str
    entity_count: int
    connection_count: int
    task_count: int
    auto_confirmed: int
    pending: int
    resolutions: list[ResolutionResult] = field(default_factory=list)


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


def _write_meeting_body(conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript) -> tuple[int, int, int, int]:
    conn_count = auto = pending = 0
    seen: set = set()
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

    task_count = 0
    with conn.cursor() as cur:
        for t in result.tasks:
            rel_id = _resolve_ref(conn, resolved, t.target_entity, transcript, on_resolved) if t.target_entity else None
            due = resolve_due_date(meeting_date, t.relative_due)
            status = _row_status(t.confidence)
            cur.execute(
                "insert into tasks (description, related_entity_id, meeting_id, due_date, confidence, "
                "source_quote, review_status) values (%s,%s,%s,%s,%s,%s,%s)",
                (t.description, rel_id, meeting_id, due, t.confidence, t.source_quote, status),
            )
            task_count += 1
            auto, pending = (auto + 1, pending) if status == "auto_confirmed" else (auto, pending + 1)

    return conn_count, task_count, auto, pending


def _finalise_meeting_status(conn, meeting_id) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update meetings set review_status = case when exists (
                select 1 from relations where meeting_id = %(m)s and review_status = 'pending'
                union all select 1 from tasks where meeting_id = %(m)s and review_status = 'pending'
                union all select 1 from entities e
                    join relations r on r.meeting_id = %(m)s and (r.source_id = e.id or r.target_id = e.id)
                    where e.review_status = 'pending'
            ) then 'pending' else 'clear' end
            where id = %(m)s
            """,
            {"m": meeting_id},
        )


def ingest_new_meeting(
    conn: psycopg.Connection,
    transcript: str,
    meeting_date: date,
    primary_contact_name: Optional[str] = None,
    location: Optional[str] = None,
    audio_path: Optional[str] = None,
    on_resolved: OnResolved = None,
) -> IngestResult:
    try:
        result = extract(transcript)
        resolved = _resolve_entities(conn, result.entities, transcript, on_resolved)

        primary_id = None
        if primary_contact_name:
            primary_id = _resolve_ref(conn, resolved, primary_contact_name, transcript, on_resolved, fallback="person")

        with conn.cursor() as cur:
            cur.execute(
                "insert into meetings (meeting_date, primary_contact_id, location, raw_transcript, audio_url, summary) "
                "values (%s,%s,%s,%s,%s,%s) returning id",
                (meeting_date, primary_id, location, transcript, audio_path, result.summary),
            )
            (meeting_id,) = cur.fetchone()

        cc, tc, auto, pending = _write_meeting_body(
            conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript
        )
        _finalise_meeting_status(conn, meeting_id)
        conn.commit()
        return IngestResult(str(meeting_id), len(resolved), cc, tc, auto, pending, list(resolved.values()))
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

        result = extract(transcript)
        resolved = _resolve_entities(conn, result.entities, transcript, on_resolved)
        cc, tc, auto, pending = _write_meeting_body(
            conn, result, resolved, on_resolved, meeting_id, meeting_date, transcript
        )
        _finalise_meeting_status(conn, meeting_id)
        conn.commit()
        return IngestResult(str(meeting_id), len(resolved), cc, tc, auto, pending, list(resolved.values()))
    except Exception as exc:
        conn.rollback()
        record_failure(conn, meeting_date or date.today(), audio_path, transcript, exc)
        raise
