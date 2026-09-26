"""Show what a question would be answered from, without answering it.

Prints the entities recognised in the question, the records gathered for them,
and how much of the meeting transcripts would fit. No model call at all, so the
whole retrieval half can be checked for free and as often as you like.

Usage: show_fact_pack.py "what is pending with Vishal"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.query.budget import FACT_SHARE, MAX_CONTEXT_CHARS, pack_notes
from app.query.facts import build_fact_pack, render_fact_pack
from app.query.retrieve import (
    meetings_for_any,
    meetings_for_entity,
    meetings_for_pair,
    recent_meetings,
    resolve_mentions,
)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: show_fact_pack.py "<question>"')
    question = " ".join(sys.argv[1:])

    conn = get_connection()
    try:
        mentions = resolve_mentions(conn, question)
        ids = [eid for eid, _ in mentions]
        print(f"QUESTION: {question}")
        print("RECOGNISED:", ", ".join(name for _, name in mentions) or "(nobody - keyword slice)")

        if len(ids) >= 2:
            notes = meetings_for_pair(conn, ids[0], ids[1]) or meetings_for_any(conn, ids)
        elif len(ids) == 1:
            notes = meetings_for_entity(conn, ids[0])
        else:
            notes = recent_meetings(conn)

        fact_budget = int(MAX_CONTEXT_CHARS * FACT_SHARE)
        pack = build_fact_pack(conn, ids, question, max_chars=fact_budget)
        spent = sum(len(f.text) for f in pack.facts)
        packed, dropped = pack_notes(notes, budget=MAX_CONTEXT_CHARS - spent)
    finally:
        release_connection(conn)

    print(f"\nRECORDS ({len(pack.facts)}):")
    print(render_fact_pack(pack) or "  (none)")

    full = sum(1 for p in packed if p.full)
    print(f"\nMEETING NOTES: {len(notes)} found, {full} sent whole, "
          f"{len(packed) - full} as summary only, {dropped} left out")
    for p in packed:
        size = len(p.note.transcript or "") if p.full else len(p.note.summary or "")
        print(f"  {p.note.meeting_date}  {'full   ' if p.full else 'summary'}  {size:>6} chars  "
              f"{p.note.primary_contact_name or ''}")

    total = spent + sum(len(p.note.transcript if p.full else (p.note.summary or "")) for p in packed)
    print(f"\nprompt material: ~{total} chars (cap {MAX_CONTEXT_CHARS})")


if __name__ == "__main__":
    main()
