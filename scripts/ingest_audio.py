"""Ingest one meeting: transcribe audio (or use a text transcript) ->
extract structured entities/relationships/tasks -> resolve entities against
the DB -> resolve relative due dates -> write meeting/relations/tasks rows ->
generate and store minutes.

Use --dry-run to just print the extraction JSON without touching the DB
(useful while iterating on the prompt).

Use --append-to-meeting <id> for a correction: the primary path for fixing
missed/wrong extractions is another voice note that goes back through this
same pipeline and appends relations/tasks to the existing meeting, rather
than creating a new one. Reuses meeting_date/primary_contact from the
original meeting; regenerates minutes afterward.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.entity_resolution.resolve import resolve_entity
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.failures import record_failure
from app.minutes.generate import store_minutes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest one meeting recording or transcript.")
    parser.add_argument("--audio", help="Path to an audio file to transcribe with faster-whisper")
    parser.add_argument("--transcript-file", help="Path to a plain-text transcript, bypassing transcription")
    parser.add_argument("--meeting-date", help="Meeting date, YYYY-MM-DD (ignored with --append-to-meeting)")
    parser.add_argument(
        "--primary-contact",
        help="Name of the main person met with (must match one of the extracted entity names)",
    )
    parser.add_argument("--location", default=None, help="Optional meeting location")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print extraction JSON only, no DB writes (step-2-style behavior)",
    )
    parser.add_argument(
        "--append-to-meeting",
        default=None,
        help="Meeting id to append this transcript's relations/tasks to, instead of creating a new meeting "
        "(the correction workflow: a follow-up voice note fixing/adding to an existing meeting)",
    )
    return parser.parse_args()


def resolve_all_entities(conn, entities) -> dict[str, "object"]:
    """Returns {extracted_name: ResolutionResult}."""
    resolved = {}
    for entity in entities:
        result = resolve_entity(conn, entity.name, entity.entity_type)
        resolved[entity.name] = result
        note = f" -> matched existing '{result.canonical_name}'" if result.outcome != "created" else " -> new entity"
        print(f"  [{result.outcome}] {entity.name} ({entity.entity_type}){note}")
    return resolved


def resolve_name(conn, resolved: dict, name: str, fallback_entity_type: str = "company"):
    """Look up an already-resolved entity by name; if a relationship/task
    references a name that wasn't in the entities list (extraction
    inconsistency), resolve it on the fly instead of failing the whole run."""
    if name in resolved:
        return resolved[name].entity_id
    print(f"  [warning] '{name}' wasn't in the extracted entities list; resolving on the fly as {fallback_entity_type}")
    result = resolve_entity(conn, name, fallback_entity_type)
    resolved[name] = result
    return result.entity_id


def get_existing_meeting(conn, meeting_id: str) -> tuple[date, str]:
    with conn.cursor() as cur:
        cur.execute("select meeting_date, primary_contact_id from meetings where id = %s", (meeting_id,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"No meeting found with id {meeting_id!r}")
        return row[0], str(row[1]) if row[1] else None


def get_existing_relation_keys(conn, meeting_id: str) -> set:
    """Pre-seed dedup with what's already on this meeting, so a correction
    that accidentally restates something already captured doesn't insert a
    same-meeting duplicate (cross-meeting duplicates are fine - that's how
    corroboration works)."""
    with conn.cursor() as cur:
        cur.execute("select source_id, relation_type, target_id from relations where meeting_id = %s", (meeting_id,))
        return {(str(s), r, str(t)) for s, r, t in cur.fetchall()}


def main() -> None:
    args = parse_args()
    if not args.audio and not args.transcript_file:
        raise SystemExit("Pass either --audio or --transcript-file")

    if args.transcript_file:
        transcript = Path(args.transcript_file).read_text(encoding="utf-8")
    else:
        from app.transcription.whisper_client import transcribe

        transcript = transcribe(args.audio)

    if args.dry_run:
        # Dev/iteration mode only - no real meeting is at stake here, so a
        # failure is just a normal crash, not something that needs a
        # persisted retry record.
        if not args.meeting_date:
            raise SystemExit("--dry-run still needs --meeting-date (used only to resolve due dates for display)")
        meeting_date = datetime.strptime(args.meeting_date, "%Y-%m-%d").date()
        result = extract(transcript)
        output = {
            "transcript": transcript,
            "entities": [e.model_dump() for e in result.entities],
            "relationships": [r.model_dump() for r in result.relationships],
            "tasks": [
                {
                    "description": t.description,
                    "target_entity": t.target_entity,
                    "relative_due": t.relative_due.model_dump() if t.relative_due else None,
                    "due_date": (
                        resolve_due_date(meeting_date, t.relative_due).isoformat() if t.relative_due else None
                    ),
                }
                for t in result.tasks
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # From here on, a failure means a real meeting could be lost - anything
    # that goes wrong (extraction, resolution, or the DB writes themselves)
    # must fail loudly and get a persisted retry record, never just an
    # exception nobody sees.
    conn = None
    meeting_date = None
    try:
        conn = get_connection()

        if args.append_to_meeting:
            meeting_id = args.append_to_meeting
            meeting_date, primary_contact_id = get_existing_meeting(conn, meeting_id)
            seen_relations = get_existing_relation_keys(conn, meeting_id)
            print(f"Appending to existing meeting {meeting_id} (date {meeting_date})")

            # The correction's own transcript needs to stay verifiable too -
            # append it to raw_transcript so the minutes still let the user
            # check extraction against what was actually said, for this
            # voice note and not just the original.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update meetings
                    set raw_transcript = raw_transcript || %s
                    where id = %s
                    """,
                    (f"\n\n--- Correction (appended {date.today().isoformat()}) ---\n\n{transcript}", meeting_id),
                )
        else:
            if not args.meeting_date:
                raise SystemExit("Pass --meeting-date (required for a new meeting)")
            if not args.primary_contact:
                raise SystemExit("Pass --primary-contact (required for a new meeting; use --dry-run to skip)")
            meeting_date = datetime.strptime(args.meeting_date, "%Y-%m-%d").date()
            seen_relations = set()

        result = extract(transcript)

        print("Resolving entities...")
        resolved = resolve_all_entities(conn, result.entities)

        if not args.append_to_meeting:
            primary_contact_id = resolve_name(conn, resolved, args.primary_contact, fallback_entity_type="person")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into meetings (meeting_date, primary_contact_id, location, raw_transcript, audio_url)
                    values (%s, %s, %s, %s, %s)
                    returning id
                    """,
                    (meeting_date, primary_contact_id, args.location, transcript, args.audio),
                )
                (meeting_id,) = cur.fetchone()

        relation_count = 0
        with conn.cursor() as cur:
            for triple in result.relationships:
                source_id = resolve_name(conn, resolved, triple.source)
                target_id = resolve_name(conn, resolved, triple.target)
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
                related_entity_id = resolve_name(conn, resolved, task.target_entity) if task.target_entity else None
                due_date = resolve_due_date(meeting_date, task.relative_due)
                cur.execute(
                    """
                    insert into tasks (description, related_entity_id, meeting_id, due_date)
                    values (%s, %s, %s, %s)
                    """,
                    (task.description, related_entity_id, meeting_id, due_date),
                )
                task_count += 1

        minutes = store_minutes(conn, meeting_id)

        conn.commit()
        print(f"\nCommitted: meeting {meeting_id}, {relation_count} relations, {task_count} tasks.")
        print("\n" + minutes)
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        record_failure(conn, meeting_date or date.today(), args.audio, transcript, exc)
        raise
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
