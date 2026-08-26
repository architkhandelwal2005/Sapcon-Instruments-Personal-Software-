import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import psycopg

# Last-resort record if the DB itself is unreachable — even then, nothing
# gets lost silently.
FALLBACK_DIR = Path(__file__).resolve().parent.parent.parent / "failed_ingestions"


def classify_error(exc: Exception) -> str:
    """Best-effort classification across both extraction providers. Checked
    against the actual installed SDK error hierarchies, not guessed:
    - anthropic: RateLimitError < APIStatusError < APIError; APIConnectionError < APIError
    - google-genai: ClientError/ServerError < APIError, with a numeric .code
    """
    try:
        import anthropic

        if isinstance(exc, anthropic.RateLimitError):
            return "rate_limit"
        if isinstance(exc, anthropic.APIConnectionError):
            return "network_error"
        if isinstance(exc, anthropic.APIError):
            return "api_error"
    except ImportError:
        pass

    try:
        from google.genai import errors as genai_errors

        if isinstance(exc, genai_errors.APIError):
            return "rate_limit" if getattr(exc, "code", None) == 429 else "api_error"
    except ImportError:
        pass

    try:
        import pydantic

        if isinstance(exc, pydantic.ValidationError):
            return "validation_error"
    except ImportError:
        pass

    return "unknown_error"


def record_failure(
    conn: Optional[psycopg.Connection],
    meeting_date: date,
    audio_path: Optional[str],
    raw_transcript: Optional[str],
    exc: Exception,
) -> None:
    """Log loudly and persist a retryable record of a failed ingestion — to
    the DB if reachable, otherwise to a local fallback file. Never let a
    failure just vanish."""
    error_type = classify_error(exc)

    print("\n" + "=" * 70, file=sys.stderr)
    print("INGESTION FAILED — this meeting was NOT saved. It needs a retry.", file=sys.stderr)
    print(f"  meeting_date : {meeting_date}", file=sys.stderr)
    print(f"  audio_path   : {audio_path}", file=sys.stderr)
    print(f"  error_type   : {error_type}", file=sys.stderr)
    print(f"  error        : {exc}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ingestion_failures
                        (meeting_date, audio_path, raw_transcript, error_type, error_message)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (meeting_date, audio_path, raw_transcript, error_type, str(exc)),
                )
            conn.commit()
            print("Recorded in ingestion_failures table for retry.\n", file=sys.stderr)
            return
        except Exception as record_exc:
            print(f"Could not record failure in the DB either: {record_exc}", file=sys.stderr)

    FALLBACK_DIR.mkdir(exist_ok=True)
    fallback_path = FALLBACK_DIR / f"{datetime.now():%Y%m%dT%H%M%S}.json"
    fallback_path.write_text(
        json.dumps(
            {
                "meeting_date": meeting_date.isoformat(),
                "audio_path": audio_path,
                "raw_transcript": raw_transcript,
                "error_type": error_type,
                "error_message": str(exc),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"DB unreachable — wrote fallback failure record to {fallback_path}\n", file=sys.stderr)
