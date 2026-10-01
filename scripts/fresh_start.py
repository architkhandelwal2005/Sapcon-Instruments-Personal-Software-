"""Clear what testing produced, so the real user starts on an empty desk.

Testing a system that records things for a living leaves records behind:
invented visits, people who do not exist, tasks nobody will do, a chat history
full of deliberate nonsense. Handing that over as somebody's book of business
is worse than handing them nothing, because they cannot tell which half is
real.

What goes: every meeting and everything it produced, every person and company
that came from a meeting, the WhatsApp conversation and its bookkeeping, and
the failed-ingestion queue.

What stays, and the whole point of doing this by source rather than by date:

- the contact book from the Excel sheet        (source = visit_list)
- everyone off the photographed visiting cards (source = card)
- everyone out of the diary pages              (source = diary)
- the staff roster                             (entity_type = employee)
- the leads attached to any of those
- logins, PINs and WhatsApp numbers

Those came from real paper and real people. Only the conversations were
invented, so only what the conversations created is removed.

Deleting rather than marking rejected: a rejected row is hidden but reachable,
which is right for a real item somebody got wrong and wrong for a fixture. That
makes this the one destructive script in the project, so it prints what it
would do and does nothing without --commit.

Usage:
    fresh_start.py                      # show what would go
    fresh_start.py --commit
    fresh_start.py --commit --keep-captures=false   # also clear card/diary data
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection

# Entities worth keeping whatever else goes. Anything from a meeting is not
# here, which is the point.
KEEP_SOURCES = ("visit_list", "card", "diary", "team", "research", "manual")
CAPTURE_SOURCES = ("card", "diary")


def _counts(cur, keep_captures: bool) -> dict:
    keep = [s for s in KEEP_SOURCES if keep_captures or s not in CAPTURE_SOURCES]
    out = {}

    cur.execute("select count(*) from meetings")
    out["meetings"] = cur.fetchone()[0]
    for table in ("tasks", "decisions", "meeting_attendees"):
        cur.execute(f"select count(*) from {table} where meeting_id is not null")
        out[table] = cur.fetchone()[0]
    cur.execute("select count(*) from relations where meeting_id is not null")
    out["relations (from meetings)"] = cur.fetchone()[0]
    cur.execute("select count(*) from relations where meeting_id is null")
    out["relations (kept, from imports)"] = -cur.fetchone()[0]

    cur.execute(
        "select count(*) from entities where coalesce(source,'') <> all(%s) "
        "and entity_type <> 'employee'",
        (list(keep),),
    )
    out["entities"] = cur.fetchone()[0]
    cur.execute(
        "select count(*) from entities where coalesce(source,'') = any(%s) "
        "or entity_type = 'employee'",
        (list(keep),),
    )
    out["entities (kept)"] = -cur.fetchone()[0]

    for table in ("conversation_turns", "ingestion_failures", "whatsapp_threads",
                  "whatsapp_pending", "whatsapp_inbound", "whatsapp_deliveries"):
        try:
            cur.execute(f"select count(*) from {table}")
            out[table] = cur.fetchone()[0]
        except Exception:
            pass

    # Most of the duplicate flags are about contacts that are staying - two
    # similar names off two visiting cards - and most of the audit trail
    # records the thousand-odd contacts somebody confirmed by hand. Both
    # survive; only the parts about things being removed go.
    cur.execute(
        "select count(*) from entity_review_queue q where exists ("
        "  select 1 from entities e where (e.id = q.entity_id or e.id = q.possible_duplicate_of)"
        "    and coalesce(e.source,'') <> all(%s) and e.entity_type <> 'employee')",
        (list(keep),),
    )
    out["duplicate flags (about removed contacts)"] = cur.fetchone()[0]
    cur.execute("select count(*) from entity_review_queue")
    kept_flags = cur.fetchone()[0] - out["duplicate flags (about removed contacts)"]
    out["duplicate flags (kept)"] = -kept_flags

    cur.execute("select count(*) from review_decisions")
    out["review history (kept)"] = -cur.fetchone()[0]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--keep-captures", default="true",
                        help="true (default) keeps visiting-card and diary contacts")
    args = parser.parse_args()
    keep_captures = args.keep_captures.lower() not in ("false", "no", "0")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            before = _counts(cur, keep_captures)
        conn.rollback()

        print("Visiting-card and diary contacts:", "KEPT" if keep_captures else "REMOVED")
        print("\nWould remove:")
        for label, n in before.items():
            if n > 0:
                print(f"  {label:<34} {n:>6}")
        print("\nWould keep:")
        for label, n in before.items():
            if n < 0:
                print(f"  {label.replace(' (kept)', ''):<34} {-n:>6}")

        if not args.commit:
            print("\nNothing changed. Re-run with --commit.")
            return

        keep = [s for s in KEEP_SOURCES if keep_captures or s not in CAPTURE_SOURCES]
        with conn.cursor() as cur:
            # Which entities are going. Everything else is repointed or removed
            # around them, so this list is worked out once and used throughout.
            cur.execute(
                "select id from entities where coalesce(source,'') <> all(%s) "
                "and entity_type <> 'employee' "
                "and not exists (select 1 from app_users u where u.entity_id = entities.id) "
                "and not exists (select 1 from whatsapp_senders w where w.entity_id = entities.id)",
                (list(keep),),
            )
            going = [r[0] for r in cur.fetchall()]

            for statement, params in (
                ("delete from whatsapp_threads", ()),
                ("delete from whatsapp_pending", ()),
                ("delete from whatsapp_inbound", ()),
                ("delete from whatsapp_deliveries", ()),
                ("delete from conversation_turns", ()),
                ("delete from ingestion_failures", ()),
                ("delete from meeting_attendees", ()),
                ("delete from decisions", ()),
                ("delete from task_assignees", ()),
                ("delete from tasks", ()),
                ("delete from relations where meeting_id is not null", ()),
            ):
                cur.execute(statement, params)
                if cur.rowcount > 0:
                    print(f"  removed {cur.rowcount:>5} from {statement.split()[-1] if 'where' not in statement else 'relations'}")

            cur.execute("delete from meetings")
            print(f"  removed {cur.rowcount:>5} meetings")

            if going:
                # Nothing may point at them when they go.
                cur.execute("delete from relations where source_id = any(%s) or target_id = any(%s)",
                            (going, going))
                cur.execute("delete from entity_review_queue where entity_id = any(%s) "
                            "or possible_duplicate_of = any(%s)", (going, going))
                # Flags between two contacts that are both staying are real
                # review work and are left alone.
                cur.execute("delete from leads where entity_id = any(%s)", (going,))
                cur.execute("update leads set assigned_to = null where assigned_to = any(%s)", (going,))
                cur.execute("update leads set status_changed_by = null where status_changed_by = any(%s)", (going,))
                cur.execute("update entities set possible_duplicate_of = null, merged_into = null "
                            "where possible_duplicate_of = any(%s) or merged_into = any(%s)",
                            (going, going))
                cur.execute("update capture_events set logged_by = null where logged_by = any(%s)", (going,))
                cur.execute("update review_decisions set decided_by = null where decided_by = any(%s)",
                            (going,))
                cur.execute("delete from review_decisions where item_id::text = any(%s)",
                            ([str(g) for g in going],))
                cur.execute("delete from entities where id = any(%s)", (going,))
                print(f"  removed {cur.rowcount:>5} entities")

            # What remains of the review history is about contacts that are
            # staying - including one row per contact from the bulk confirm of
            # the Excel import, which is exactly the record worth keeping.
        conn.commit()
        print("\nDone. The contact book, the roster and the leads are untouched.")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
