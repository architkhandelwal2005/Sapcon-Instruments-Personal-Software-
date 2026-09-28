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

from app.agent import plan_message
from app.capture.storage import download
from app.db import get_connection, release_connection
from app.ingestion.pipeline import ingest_new_meeting
from app.llm import transcribe_audio
from app.transcription.vocabulary import known_names


def _waiting(conn, limit: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, meeting_date, raw_transcript, error_type, occurred_at, audio_path
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
        for _id, _date, transcript, error_type, occurred_at, audio in rows:
            head = (transcript or "").strip().replace("\n", " ")[:70]
            if not head:
                head = "(a voice note, kept)" if audio else "(nothing kept)"
            print(f"  {occurred_at:%d %b %H:%M}  {error_type:<16} {head}")

        if not args.commit:
            print("\nRe-run with --commit to reprocess them.")
            return

        print()
        for failure_id, meeting_date, transcript, _error_type, _occurred_at, audio in rows:
            if not (transcript or "").strip():
                # A voice note that was kept but never transcribed - the model
                # was refusing calls when it arrived. This is the whole reason
                # the recording is stored rather than held in memory.
                if not audio or not audio.startswith("http"):
                    print(f"  {failure_id}: nothing kept to re-run - left for a human")
                    continue
                try:
                    transcript = transcribe_audio(download(audio), "audio/ogg", known_names(conn))
                except Exception as exc:
                    print(f"  {failure_id}: still cannot transcribe - {type(exc).__name__}: {str(exc)[:70]}")
                    continue
                if not transcript.strip():
                    print(f"  {failure_id}: transcribed to nothing - left for a human")
                    continue
                with conn.cursor() as cur:
                    cur.execute("update ingestion_failures set raw_transcript = %s where id = %s",
                                (transcript, failure_id))
                conn.commit()
                print(f"  {failure_id}: transcribed - {transcript.strip()[:60]}")
            intent = plan_message(transcript, "").action
            if intent != "log":
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
                result = ingest_new_meeting(conn, transcript, meeting_date, record_failures=False)
            except Exception as exc:
                # The row stays unresolved and keeps its place in the queue.
                # Filing a second copy is how draining the queue used to make
                # it longer.
                with conn.cursor() as cur:
                    cur.execute(
                        "update ingestion_failures set error_message = %s where id = %s",
                        (f"{type(exc).__name__}: {exc}"[:2000], failure_id),
                    )
                conn.commit()
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
