"""Who has been talked about lately.

A bare first name in a note nearly always means somebody already on his mind.
Without that, resolving "Rajesh" is a choice between strangers who share a
name, and the honest answer is "uncertain" - which creates a second Rajesh and
a flag, the day after a long note about Rajesh Sharma.
"""

from datetime import timedelta

import psycopg

WINDOW_DAYS = 7
MAX_NAMES = 60

_CACHE: dict = {}
_CACHE_FOR = timedelta(minutes=10)


def recently_discussed(conn: psycopg.Connection) -> set:
    """Names from meetings in the last week.

    Cached briefly: one ingest resolves a dozen names and would otherwise ask
    the same question a dozen times, and the answer cannot meaningfully change
    inside one note."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    cached = _CACHE.get("names")
    if cached and now - cached[0] < _CACHE_FOR:
        return cached[1]

    names = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select distinct e.canonical_name
                from entities e
                join relations r on (r.source_id = e.id or r.target_id = e.id)
                join meetings m on m.id = r.meeting_id
                where m.meeting_date >= current_date - %(days)s
                  and r.review_status <> 'rejected'
                  and e.review_status <> 'rejected'
                limit %(cap)s
                """,
                {"days": WINDOW_DAYS, "cap": MAX_NAMES},
            )
            names = {r[0] for r in cur.fetchall()}
        conn.rollback()
    except Exception:
        conn.rollback()
        return set()

    _CACHE["names"] = (now, names)
    return names
