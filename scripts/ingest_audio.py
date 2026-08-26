"""CLI entrypoint - a thin wrapper around app.ingestion.pipeline (shared with
the web app's correction form, so both go through one code path).

Transcribe audio (or use a text transcript) -> extract structured
entities/relationships/tasks -> resolve entities against the DB -> resolve
relative due dates -> write meeting/relations/tasks rows -> generate and
store minutes.

Use --dry-run to just print the extraction JSON without touching the DB
(useful while iterating on the prompt).

Use --append-to-meeting <id> for a correction: the primary path for fixing
missed/wrong extractions is another voice note that goes back through this
same pipeline and appends relations/tasks to the existing meeting, rather
than creating a new one.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.pipeline import append_correction, ingest_new_meeting


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


def _print_resolution(entry) -> None:
    note = f" -> matched existing '{entry.canonical_name}'" if entry.outcome != "created" else " -> new entity"
    print(f"  [{entry.outcome}] {entry.name} ({entry.entity_type}){note}")


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

    conn = get_connection()
    try:
        if args.append_to_meeting:
            print(f"Appending to existing meeting {args.append_to_meeting}")
            print("Resolving entities...")
            ingest_result = append_correction(
                conn, args.append_to_meeting, transcript, audio_path=args.audio, on_resolved=_print_resolution
            )
        else:
            if not args.meeting_date:
                raise SystemExit("Pass --meeting-date (required for a new meeting)")
            if not args.primary_contact:
                raise SystemExit("Pass --primary-contact (required for a new meeting; use --dry-run to skip)")
            meeting_date = datetime.strptime(args.meeting_date, "%Y-%m-%d").date()
            print("Resolving entities...")
            ingest_result = ingest_new_meeting(
                conn,
                transcript,
                meeting_date,
                args.primary_contact,
                location=args.location,
                audio_path=args.audio,
                on_resolved=_print_resolution,
            )

        print(
            f"\nCommitted: meeting {ingest_result.meeting_id}, "
            f"{ingest_result.relation_count} relations, {ingest_result.task_count} tasks."
        )
        print("\n" + ingest_result.minutes)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
