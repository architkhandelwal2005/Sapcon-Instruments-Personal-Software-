"""Whether a message we sent actually reached the phone.

Meta answers a send with a message id straight away. That id means accepted,
not delivered. The real outcome arrives minutes later as a status callback on
the same webhook, and those were being discarded - so a message Meta dropped
looked identical to one that arrived. Two real messages were reported as sent
and never existed on anybody's phone.

The common reason for a drop is error 131047: outside the 24-hour window, a
business may not open a conversation with free-form text. That is a rule, not a
bug, and the system has to be able to see it to say so.
"""

import sys
from typing import Optional

import psycopg

# Meta's code for "you may not start this conversation" - the one failure that
# is about the rules rather than about the phone.
RE_ENGAGEMENT = 131047

_HUMAN = {
    RE_ENGAGEMENT: "outside the 24-hour window - they must message first, or it needs a template",
    131026: "the number cannot receive WhatsApp messages",
    131051: "unsupported message type",
    470: "outside the 24-hour window",
}


def statuses(payload: dict) -> list[dict]:
    """The delivery-status entries in a webhook payload, if any."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            out.extend((change.get("value") or {}).get("statuses") or [])
    return out


def record_sent(conn: psycopg.Connection, wa_message_id: Optional[str], recipient: str) -> None:
    """Note that we handed a message to Meta. Losing this row costs a delivery
    record, never the message, so it never raises."""
    if not wa_message_id:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into whatsapp_deliveries (wa_message_id, recipient, status) "
                "values (%s, %s, 'sent') on conflict (wa_message_id) do nothing",
                (wa_message_id, recipient),
            )
        conn.commit()
    except Exception:
        conn.rollback()


def record_status(conn: psycopg.Connection, status: dict) -> None:
    """Apply one status callback. A failure is printed as well as stored, so it
    shows up in the server log where somebody is already looking."""
    wa_message_id = status.get("id")
    if not wa_message_id:
        return
    state = (status.get("status") or "").lower()
    errors = status.get("errors") or []
    code = errors[0].get("code") if errors else None
    title = errors[0].get("title") if errors else None

    if state == "failed":
        print(
            f"WHATSAPP DELIVERY FAILED to {status.get('recipient_id')}: "
            f"{code} {title} - {_HUMAN.get(code, 'see Meta error reference')}",
            file=sys.stderr,
        )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into whatsapp_deliveries
                    (wa_message_id, recipient, status, error_code, error_title)
                values (%s, %s, %s, %s, %s)
                on conflict (wa_message_id) do update set
                    status = excluded.status,
                    error_code = coalesce(excluded.error_code, whatsapp_deliveries.error_code),
                    error_title = coalesce(excluded.error_title, whatsapp_deliveries.error_title),
                    updated_at = now()
                """,
                (wa_message_id, status.get("recipient_id") or "", state or "unknown", code, title),
            )
        conn.commit()
    except Exception:
        conn.rollback()


def last_failure(conn: psycopg.Connection, recipient_digits: str) -> Optional[dict]:
    """The most recent failed delivery to this number, for explaining to a
    person why their message never arrived."""
    with conn.cursor() as cur:
        cur.execute(
            "select wa_message_id, error_code, error_title, updated_at "
            "from whatsapp_deliveries where recipient = %s and status = 'failed' "
            "order by updated_at desc limit 1",
            (recipient_digits,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"wa_message_id": row[0], "error_code": row[1], "error_title": row[2],
            "reason": _HUMAN.get(row[1], row[2] or "unknown"), "at": row[3]}
