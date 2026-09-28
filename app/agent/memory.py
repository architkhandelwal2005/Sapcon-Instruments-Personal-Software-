"""The last few turns of one person's conversation.

Without this every message was judged on its own, so nothing could follow on
from anything: "and Parag?" after a question about Rajesh meant nothing, and
the bot could not refer to what it had just said one line earlier.

Deliberately shallow. Six turns is enough for a follow-up question and cheap to
send with every message; a long history would cost tokens on every call and
tempt the model to answer from a stale memory of a record instead of from the
record. Facts live in the database, not in here.
"""

from typing import Optional

import psycopg

TURNS = 6
MAX_BODY = 1200          # a long readback adds nothing to the next reply


def remember_turn(conn: psycopg.Connection, sender: str, role: str, body: str) -> None:
    """Never raises: losing a turn costs the thread of a conversation, never a
    record, and must not take a reply down with it."""
    text = (body or "").strip()
    if not text:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into conversation_turns (sender, role, body) values (%s, %s, %s)",
                (sender, role, text[:MAX_BODY]),
            )
        conn.commit()
    except Exception:
        conn.rollback()


def recent(conn: psycopg.Connection, sender: str, limit: int = TURNS) -> list[tuple[str, str]]:
    """[(role, body)] oldest first, so it reads as a transcript."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select role, body from conversation_turns where sender = %s "
                "order by created_at desc, id desc limit %s",
                (sender, limit),
            )
            rows = cur.fetchall()
        conn.rollback()
    except Exception:
        conn.rollback()
        return []
    return [(r[0], r[1]) for r in reversed(rows)]


def render(turns: list[tuple[str, str]]) -> str:
    """The conversation as the model should read it."""
    if not turns:
        return "(this is the first message)"
    speaker = {"them": "Them", "us": "You"}
    return "\n".join(f"{speaker.get(role, role)}: {body}" for role, body in turns)


def last_from_us(conn: psycopg.Connection, sender: str) -> Optional[str]:
    for role, body in reversed(recent(conn, sender)):
        if role == "us":
            return body
    return None
