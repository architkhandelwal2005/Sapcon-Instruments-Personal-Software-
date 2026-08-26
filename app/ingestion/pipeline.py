"""Shared ingestion pipeline used by both the CLI (scripts/ingest_audio.py)
and the web app's correction form - one code path, so a correction behaves
identically no matter how it was submitted.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import psycopg

from app.entity_resolution.resolve import resolve_entity
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.failures import record_failure
from app.minutes.generate import store_minutes


@dataclass
class ResolutionLogEntry:
    name: str
    entity_type: str
    outcome: str
    canonical_name: str
    possible_duplicate_of: Optional[str] = None


@dataclass
class IngestResult:
    meeting_id: str
    relation_count: int
    task_count: int
    minutes: str
    resolution_log: list[ResolutionLogEntry]


OnResolved = Optional[Callable[[ResolutionLogEntry], None]]


def _resolve_all_entities(
    conn, entities, on_resolved: OnResolved = None, interactive: bool = True
) -> tuple[dict, list[ResolutionLogEntry]]:
    resolved = {}
    log: list[ResolutionLogEntry] = []
    for entity in entities:
        result = resolve_entity(conn, entity.name, entity.entity_type, interactive=interactive)
        resolved[entity.name] = result
        entry = ResolutionLogEntry(
            entity.name, entity.entity_type, result.outcome, result.canonical_name, result.possible_duplicate_of
        )
        log.append(entry)
        if on_resolved:
            on_resolved(entry)
    return resolved, log


def _resolve_name(
    conn, resolved: dict, name: str, log: list, on_resolved: OnResolved, interactive: bool, fallback_entity_type: str = "company"
):
    """Look up an already-resolved entity by name; if a relationship/task
    references a name that wasn't in the extracted entities list (extraction
    inconsistency), resolve it on the fly instead of failing the whole run."""
    if name in resolved:
        return resolved[name].entity_id
    result = resolve_entity(conn, name, fallback_entity_type, interactive=interactive)
    resolved[name] = result
    entry = ResolutionLogEntry(
        name, fallback_entity_type, result.outcome, result.canonical_name, result.possible_duplicate_of
    )
    log.append(entry)
    if on_resolved:
        on_resolved(entry)
    return result.entity_id


def get_existing_meeting(conn, meeting_id: str) -> tuple[date, Optional[str]]:
    with conn.cursor() as cur:
        cur.execute("select meeting_date, primary_contact_id from meetings where id = %s", (meeting_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No meeting found with id {meeting_id!r}")
        return row[0], (str(row[1]) if row[1] else None)


def _get_existing_relation_keys(conn, meeting_id: str) -> set:
    """Pre-seed dedup with what's already on this meeting, so a correction
    that accidentally restates something already captured doesn't insert a
    same-meeting duplicate (cross-meeting duplicates are fine - that's how
    corroboration works)."""
    with conn.cursor() as cur:
        cur.execute("select source_id, relation_type, target_id from relations where meeting_id = %s", (meeting_id,))
        return {(str(s), r, str(t)) for s, r, t in cur.fetchall()}


def _write_relations_and_tasks(
    conn, result, resolved, log, on_resolved, meeting_id, meeting_date, seen_relations, interactive: bool
) -> tuple[int, int]:
    relation_count = 0
    with conn.cursor() as cur:
        for triple in result.relationships:
            source_id = _resolve_name(conn, resolved, triple.source, log, on_resolved, interactive)
            target_id = _resolve_name(conn, resolved, triple.target, log, on_resolved, interactive)
            key = (source_id, triple.relation, target_id)
            if key in seen_relations:
                continue
            seen_relations.add(key)
            cur.execute(
                """
                insert into relations (source_id, target_id, relation_type, meeting_id, provenance, recorded_at)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (source_id, target_id, triple.relation, meeting_id, triple.provenance, meeting_date),
            )
            relation_count += 1

    task_count = 0
    with conn.cursor() as cur:
        for task in result.tasks:
            related_entity_id = (
                _resolve_name(conn, resolved, task.target_entity, log, on_resolved, interactive)
                if task.target_entity
                else None
            )
            due_date = resolve_due_date(meeting_date, task.relative_due)
            cur.execute(
                """
                insert into tasks (description, related_entity_id, meeting_id, due_date)
                values (%s, %s, %s, %s)
                """,
                (task.description, related_entity_id, meeting_id, due_date),
            )
            task_count += 1

    return relation_count, task_count


def ingest_new_meeting(
    conn: psycopg.Connection,
    transcript: str,
    meeting_date: date,
    primary_contact_name: str,
    location: Optional[str] = None,
    audio_path: Optional[str] = None,
    on_resolved: OnResolved = None,
    interactive: bool = True,
) -> IngestResult:
    """Create a brand-new meeting from a transcript. Commits on success;
    rolls back and records a retryable failure (see app.ingestion.failures)
    on any error.

    interactive=False must be used from any non-terminal caller (e.g. a web
    request) - see resolve_entity()'s docstring for why: the confirm-queue
    reads from stdin and would hang the caller forever otherwise.
    """
    try:
        result = extract(transcript)
        resolved, log = _resolve_all_entities(conn, result.entities, on_resolved, interactive)
        primary_contact_id = _resolve_name(
            conn, resolved, primary_contact_name, log, on_resolved, interactive, fallback_entity_type="person"
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                insert into meetings (meeting_date, primary_contact_id, location, raw_transcript, audio_url)
                values (%s, %s, %s, %s, %s)
                returning id
                """,
                (meeting_date, primary_contact_id, location, transcript, audio_path),
            )
            (meeting_id,) = cur.fetchone()

        relation_count, task_count = _write_relations_and_tasks(
            conn, result, resolved, log, on_resolved, meeting_id, meeting_date, set(), interactive
        )
        minutes = store_minutes(conn, meeting_id)
        conn.commit()
        return IngestResult(str(meeting_id), relation_count, task_count, minutes, log)
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
    interactive: bool = True,
) -> IngestResult:
    """Append a correction voice note/text to an existing meeting: resolves
    entities against the whole DB as usual, dedupes relations already on
    this meeting, preserves the correction's own transcript text alongside
    the original, and regenerates minutes. Commits on success; rolls back
    and records a retryable failure on any error.

    interactive=False must be used from any non-terminal caller - see
    ingest_new_meeting()'s docstring.
    """
    meeting_date = None
    try:
        meeting_date, _ = get_existing_meeting(conn, meeting_id)
        seen_relations = _get_existing_relation_keys(conn, meeting_id)

        with conn.cursor() as cur:
            cur.execute(
                "update meetings set raw_transcript = raw_transcript || %s where id = %s",
                (f"\n\n--- Correction (appended {date.today().isoformat()}) ---\n\n{transcript}", meeting_id),
            )

        result = extract(transcript)
        resolved, log = _resolve_all_entities(conn, result.entities, on_resolved, interactive)

        relation_count, task_count = _write_relations_and_tasks(
            conn, result, resolved, log, on_resolved, meeting_id, meeting_date, seen_relations, interactive
        )
        minutes = store_minutes(conn, meeting_id)
        conn.commit()
        return IngestResult(meeting_id, relation_count, task_count, minutes, log)
    except Exception as exc:
        conn.rollback()
        record_failure(conn, meeting_date or date.today(), audio_path, transcript, exc)
        raise
