"""Reprocess notes that failed the first time.

When ingestion throws, the note is kept in ingestion_failures and the sender is
told "it's saved, we'll follow up". Until now nothing could follow up: there was
no retry path at all, so the reply was a promise the system could not keep.

Every failure carries the transcript that was already produced, so a retry costs
extraction and resolution but not transcription. A row whose transcript is empty
is left alone and reported - there is nothing to re-run, and marking it resolved
would quietly bury it.

The queue predates the three-way intent check, so it holds greetings and
questions that were filed as notes because there was no other category. Each one
is classified before it is re-run: only a real note becomes a meeting, and the
rest are closed with the reason recorded. Re-running them blind would manufacture
exactly the junk rows that check was added to stop.

Usage:
    retry_failures.py                 # show what is waiting
    retry_failures.py --commit        # actually reprocess
    retry_failures.py --commit --limit 5
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.ingestion.pipeline import ingest_new_meeting
from app.whatsapp.intent import classify


def _waiting(conn, limit: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, meeting_date, raw_transcript, error_type, occurred_at
            from ingestion_failures
            where not resolved
            order by occurred_at
            limit %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    conn.rollback()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="reprocess, rather than just listing")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    conn = get_connection()
    try:
        rows = _waiting(conn, args.limit)
        if not rows:
            print("Nothing waiting.")
            return

        print(f"{len(rows)} note(s) waiting:\n")
        for failure_id, meeting_date, transcript, error_type, occurred_at in rows:
            head = (transcript or "").strip().replace("\n", " ")[:70]
            print(f"  {occurred_at:%d %b %H:%M}  {error_type:<16} {head or '(no transcript)'}")

        if not args.commit:
            print("\nRe-run with --commit to reprocess them.")
            return

        print()
        for failure_id, meeting_date, transcript, _error_type, _occurred_at in rows:
            if not (transcript or "").strip():
                print(f"  {failure_id}: no transcript to re-run - left for a human")
                continue
            intent = classify(transcript)
            if intent != "note":
                with conn.cursor() as cur:
                    cur.execute(
                        "update ingestion_failures set resolved = true, "
                        "error_message = error_message || %s where id = %s",
                        (f" | closed on retry: {intent}, not a note", failure_id),
                    )
                conn.commit()
                print(f"  {failure_id}: {intent}, not a note - closed without filing")
                continue
            try:
                result = ingest_new_meeting(conn, transcript, meeting_date)
            except Exception as exc:
                print(f"  {failure_id}: failed again - {type(exc).__name__}: {str(exc)[:90]}")
                continue
            with conn.cursor() as cur:
                cur.execute("update ingestion_failures set resolved = true where id = %s", (failure_id,))
            conn.commit()
            print(f"  {failure_id}: logged - {result.entity_count} people/companies, "
                  f"{result.task_count} tasks -> meeting {result.meeting_id}")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
