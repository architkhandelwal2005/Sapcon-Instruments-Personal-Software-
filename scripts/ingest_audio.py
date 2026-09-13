"""CLI entrypoint - a thin wrapper around app.ingestion.pipeline (shared with
the web app), for testing the pipeline from the terminal.

transcribe audio (or use a text transcript) -> extract + verify -> resolve
entities (LLM) -> write meeting/connections/tasks, each with a confidence and
a review_status.

--dry-run  prints the extraction + verification result, no DB writes.
--append-to-meeting <id>  runs a correction against an existing meeting.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.extraction.extractor import extract
from app.extraction.resolve_dates import resolve_due_date
from app.ingestion.pipeline import append_correction, ingest_new_meeting
from app.minutes.generate import generate_readback


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest one meeting recording or transcript.")
    p.add_argument("--audio", help="audio file to transcribe with Gemini")
    p.add_argument("--transcript-file", help="plain-text transcript, bypassing transcription")
    p.add_argument("--meeting-date", help="YYYY-MM-DD (new meeting only)")
    p.add_argument("--primary-contact", help="name of the main person met (new meeting only)")
    p.add_argument("--location", default=None)
    p.add_argument("--dry-run", action="store_true", help="print extraction result, no DB writes")
    p.add_argument("--append-to-meeting", default=None, help="meeting id to append a correction to")
    return p.parse_args()


def _on_resolved(mentioned: str, r) -> None:
    if r.outcome == "linked":
        note = f"-> linked to existing '{r.canonical_name}'"
    elif r.outcome == "uncertain_created":
        note = f"-> NEW, flagged for review (possible duplicate of '{r.possible_duplicate_of}')"
    else:
        note = f"-> new entity ({r.review_status})"
    print(f"  [{r.outcome}] {mentioned} {note}  {('- ' + r.reason) if r.reason else ''}")
    for c in r.conflicts:
        print(f"      conflict: {c}")


def _read_transcript(args) -> str:
    if args.transcript_file:
        return Path(args.transcript_file).read_text(encoding="utf-8")
    if args.audio:
        import mimetypes

        from app.llm import transcribe_audio

        mime_type = mimetypes.guess_type(args.audio)[0] or "audio/ogg"
        return transcribe_audio(Path(args.audio).read_bytes(), mime_type)
    raise SystemExit("Pass either --audio or --transcript-file")


def main() -> None:
    args = parse_args()
    transcript = _read_transcript(args)

    if args.dry_run:
        meeting_date = datetime.strptime(args.meeting_date, "%Y-%m-%d").date() if args.meeting_date else None
        result = extract(transcript)
        out = {
            "summary": result.summary,
            "entities": [e.model_dump() for e in result.entities],
            "connections": [c.model_dump() for c in result.connections],
            "tasks": [
                {
                    **t.model_dump(exclude={"relative_due"}),
                    "relative_due": t.relative_due.model_dump() if t.relative_due else None,
                    "due_date": (
                        resolve_due_date(meeting_date, t.relative_due).isoformat()
                        if (t.relative_due and meeting_date)
                        else None
                    ),
                }
                for t in result.tasks
            ],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    conn = get_connection()
    try:
        print("Extracting + verifying + resolving...")
        if args.append_to_meeting:
            res = append_correction(conn, args.append_to_meeting, transcript, audio_path=args.audio, on_resolved=_on_resolved)
        else:
            if not args.meeting_date:
                raise SystemExit("--meeting-date required for a new meeting")
            meeting_date = datetime.strptime(args.meeting_date, "%Y-%m-%d").date()
            res = ingest_new_meeting(
                conn, transcript, meeting_date, args.primary_contact,
                location=args.location, audio_path=args.audio, on_resolved=_on_resolved,
            )
        print(
            f"\nmeeting {res.meeting_id}: {res.entity_count} entities, {res.connection_count} connections, "
            f"{res.task_count} tasks  ({res.auto_confirmed} auto-confirmed, {res.pending} pending review)"
        )
        print("\n" + generate_readback(conn, res.meeting_id))
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
