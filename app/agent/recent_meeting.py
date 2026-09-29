"""The meeting a correction is probably about, when he did not reply to one.

Corrections were only recognised when sent as a WhatsApp reply to the read-back
message. He sent his instead as a fresh voice note, which is what anybody would
do from a car, and every one of them was filed as a new meeting: a second
"follow up with Anil" task, a second "Anil" flagged as possibly the same person
as Anil Mehta, and the original left exactly as it was.

So a correction is now also recognised without the reply. What makes that safe
is not a time window on its own - it is that the amendment pass can only name
items from that specific meeting, and answers nothing when the message does not
correct one of them. The window only decides which meeting to offer it.

Short, deliberately. A correction follows its read-back within minutes; hours
later he is somewhere else talking about someone else, and the cost of reaching
too far back is a change to a meeting he is no longer looking at.
"""

from datetime import timedelta
from typing import Optional

import psycopg

WINDOW = timedelta(hours=3)


def latest_readback(conn: psycopg.Connection, sender_digits: str) -> Optional[str]:
    """The meeting behind the most recent read-back sent to this person, if it
    was recent enough to still be what they are looking at."""
    with conn.cursor() as cur:
        cur.execute(
            r"""
            select t.meeting_id
            from whatsapp_threads t
            left join whatsapp_senders s on s.entity_id = t.sender_entity_id
            where t.sent_at > now() - %(window)s
              and (regexp_replace(coalesce(s.phone, ''), '\D', '', 'g') = %(digits)s
                   or t.sender_entity_id is null)
            order by t.sent_at desc
            limit 1
            """,
            {"window": WINDOW, "digits": sender_digits},
        )
        row = cur.fetchone()
    conn.rollback()
    return str(row[0]) if row else None
