"""Remove what testing created, and nothing else.

Testing a system that records things for a living leaves records behind:
invented visits, people who do not exist, tasks nobody will ever do. Handing
that to somebody as their real book of business would be worse than handing
them nothing, because they cannot tell which half is which.

What this removes: meetings recorded in a date range, everything those meetings
produced, and any person or company that exists ONLY because of them.

What it keeps, and must keep: the contact book. Seventeen hundred people and
companies came from the visiting-card import and the Excel sheet, and anything
with history older than the range stays whole. A contact that testing merely
mentioned is kept too - only one that testing invented goes.

Deleting is right here rather than marking things rejected. A rejected row is
hidden but reachable, which is what you want for a real item somebody got
wrong; a test fixture should leave nothing to stumble over. That makes this the
one destructive script in the project, so it prints what it would do and does
nothing at all without --commit.

Usage:
    clear_test_data.py --from 2026-09-25              # show what would go
    clear_test_data.py --from 2026-09-25 --commit
    clear_test_data.py --from 2026-09-25 --to 2026-09-30 --commit
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection


def _meetings(cur, start: date, end: date) -> list:
    cur.execute(
        "select id, meeting_date, kind, left(coalesce(summary, raw_transcript, ''), 60) "
        "from meetings where meeting_date between %s and %s order by meeting_date, id",
        (start, end),
    )
    return cur.fetchall()


def _orphans(cur, ids: list) -> list:
    """People and companies that exist only because of these meetings.

    An entity survives if anything outside the range still points at it - an
    older meeting, a lead, a visiting card. Only one whose entire existence is
    inside the range is a test fixture."""
    if not ids:
        return []
    cur.execute(
        """
        select e.id, e.canonical_name, e.entity_type
        from entities e
        where e.source is distinct from 'visit_list'
          and e.entity_type <> 'employee'
          and e.capture_event_id is null
          and not exists (select 1 from leads l where l.entity_id = e.id or l.assigned_to = e.id)
          and not exists (select 1 from meetings m
                          where m.id <> all(%(ids)s)
                            and (m.primary_contact_id = e.id or m.logged_by = e.id))
          and not exists (select 1 from relations r
                          where r.meeting_id <> all(%(ids)s) and r.meeting_id is not null
                            and (r.source_id = e.id or r.target_id = e.id))
          and not exists (select 1 from app_users u where u.entity_id = e.id)
          and not exists (select 1 from whatsapp_senders w where w.entity_id = e.id)
          and exists (select 1 from relations r
                      where r.meeting_id = any(%(ids)s)
                        and (r.source_id = e.id or r.target_id = e.id))
        order by e.canonical_name
        """,
        {"ids": ids},
    )
    return cur.fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD, default today")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            meetings = _meetings(cur, start, end)
            ids = [m[0] for m in meetings]
            orphans = _orphans(cur, ids)
            conn.rollback()

        print(f"Meetings {start} to {end}: {len(meetings)}")
        for _mid, mdate, kind, head in meetings:
            print(f"  {mdate} {kind:<13} {head!r}")
        print(f"\nPeople and companies that exist only because of them: {len(orphans)}")
        for _eid, name, etype in orphans:
            print(f"  {name} ({etype})")

        if not args.commit:
            print("\nNothing has been changed. Re-run with --commit to remove them.")
            print("The contact book, employees, leads and anything with older history stay.")
            return

        with conn.cursor() as cur:
            for table, column in (("tasks", "meeting_id"), ("relations", "meeting_id"),
                                  ("decisions", "meeting_id"), ("meeting_attendees", "meeting_id"),
                                  ("whatsapp_threads", "meeting_id")):
                cur.execute(f"delete from {table} where {column} = any(%s)", (ids,))
                if cur.rowcount:
                    print(f"  removed {cur.rowcount} from {table}")

            orphan_ids = [o[0] for o in orphans]
            if orphan_ids:
                # Anything still pointing at them first, or the delete is refused.
                for table, column in (("entity_review_queue", "entity_id"),
                                      ("entity_review_queue", "possible_duplicate_of"),
                                      ("tasks", "related_entity_id"),
                                      ("task_assignees", "employee_id")):
                    cur.execute(f"delete from {table} where {column} = any(%s)", (orphan_ids,))
                cur.execute("update entities set possible_duplicate_of = null, merged_into = null "
                            "where possible_duplicate_of = any(%s) or merged_into = any(%s)",
                            (orphan_ids, orphan_ids))
                cur.execute("delete from entities where id = any(%s)", (orphan_ids,))
                print(f"  removed {cur.rowcount} entities")

            cur.execute("delete from meetings where id = any(%s)", (ids,))
            print(f"  removed {cur.rowcount} meetings")
        conn.commit()
        print("\nDone.")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
