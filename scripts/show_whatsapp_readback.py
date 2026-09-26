"""Print the WhatsApp readback for a meeting already in the database, with its
length, so the layout can be checked against real meetings without sending a
message or spending a model call.

Entity outcomes are reconstructed from what the rows now say, which is enough to
check layout and trimming. Only the live webhook knows whether a name was truly
linked or created at the time, so the `!` marks here are indicative.

Usage: show_whatsapp_readback.py <meeting_id> [<meeting_id> ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.entity_resolution.resolve import ResolutionResult
from app.minutes.generate import fetch_meeting_minutes_data
from app.whatsapp.readback import HARD_LIMIT, SOFT_LIMIT, meeting_readback_reply


def _resolutions(conn, meeting_id: str) -> list[ResolutionResult]:
    """Rebuild plausible resolutions from the entities this meeting touches."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct e.id, e.canonical_name, e.entity_type, e.review_status,
                   d.canonical_name
            from entities e
            left join entities d on d.id = e.possible_duplicate_of
            where e.id = (select primary_contact_id from meetings where id = %(m)s)
               or e.id in (select source_id from relations where meeting_id = %(m)s)
               or e.id in (select target_id from relations where meeting_id = %(m)s)
            """,
            {"m": meeting_id},
        )
        rows = cur.fetchall()

    out = []
    for entity_id, name, entity_type, review_status, dup_name in rows:
        if dup_name:
            outcome = "uncertain_created"
        elif review_status == "auto_confirmed":
            outcome = "linked"
        else:
            outcome = "created"
        out.append(ResolutionResult(
            entity_id=str(entity_id), outcome=outcome, canonical_name=name,
            review_status=review_status, mentioned_name=name,
            possible_duplicate_of=dup_name, entity_type=entity_type,
        ))
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: show_whatsapp_readback.py <meeting_id> [<meeting_id> ...]")

    conn = get_connection()
    try:
        for meeting_id in sys.argv[1:]:
            data = fetch_meeting_minutes_data(conn, meeting_id)
            text = meeting_readback_reply(
                data, _resolutions(conn, meeting_id),
                f"https://example.com/meetings/{meeting_id}",
            )
            print("=" * 70)
            print(text)
            print("-" * 70)
            fit = "fits" if len(text) <= SOFT_LIMIT else ("trimmed" if len(text) <= HARD_LIMIT else "TOO LONG")
            print(f"{len(text)} chars ({fit}; soft {SOFT_LIMIT}, hard {HARD_LIMIT})")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
