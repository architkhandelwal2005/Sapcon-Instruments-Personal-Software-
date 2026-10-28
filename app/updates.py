"""Updates written on a task or a lead, and the notifications people receive.

An update is the running note between "assigned" and "done": "called, they want
5% off, revising Monday". Posting one tells the people who care - the owner and
the office, and whoever the work belongs to - but never the person who wrote it.

Assignments and status changes are announced by the database itself (migration
0025), because they happen in many places. An update is only ever written here,
so it is announced here.

Nothing here commits.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg

MAX_BODY = 2000


@dataclass
class Update:
    id: int
    body: str
    author_name: Optional[str]
    created_at: datetime


@dataclass
class Notification:
    id: int
    kind: str
    body: str
    url: str
    created_at: datetime
    read: bool


def _title(conn, kind: str, item_id: str) -> Optional[str]:
    """What the item is called in a notification, or None if it does not exist."""
    with conn.cursor() as cur:
        if kind == "task":
            cur.execute("select left(description, 80) from tasks where id = %s", (item_id,))
        else:
            cur.execute("select e.canonical_name from leads l join entities e on e.id = l.entity_id "
                        "where l.id = %s", (item_id,))
        row = cur.fetchone()
    return row[0] if row else None


def _people_on(conn, kind: str, item_id: str) -> list[str]:
    """Whose work this is, plus the owner and the office."""
    with conn.cursor() as cur:
        if kind == "task":
            cur.execute("select employee_id from task_assignees "
                        "where task_id = %s and employee_id is not null", (item_id,))
        else:
            cur.execute("select assigned_to from leads where id = %s and assigned_to is not null",
                        (item_id,))
        workers = [str(r[0]) for r in cur.fetchall()]
        cur.execute("select entity_id from app_users where role in ('owner', 'office') and not disabled")
        staff = [str(r[0]) for r in cur.fetchall()]
    return list(dict.fromkeys(workers + staff))


def post(conn: psycopg.Connection, kind: str, item_id: str, body: str, *,
         author_id: str, author_name: str) -> Optional[int]:
    """Add an update and tell everyone on the item except its author. Returns
    the update id, or None when the text is empty or the item does not exist."""
    body = (body or "").strip()[:MAX_BODY]
    title = _title(conn, kind, item_id) if body else None
    if title is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "insert into updates (kind, item_id, body, author_id) values (%s, %s, %s, %s) returning id",
            (kind, item_id, body, author_id),
        )
        update_id = cur.fetchone()[0]
        short = body if len(body) <= 140 else body[:137] + "..."
        url = f"/{kind}s/{item_id}"
        for recipient in _people_on(conn, kind, item_id):
            if recipient == author_id:
                continue
            cur.execute(
                "insert into notifications (recipient_id, kind, item_kind, item_id, body, url, actor_id) "
                "values (%s, 'update', %s, %s, %s, %s, %s)",
                (recipient, kind, item_id, f"{author_name} on {title}: {short}", url, author_id),
            )
    return update_id


def for_item(conn: psycopg.Connection, kind: str, item_id: str) -> list[Update]:
    """Oldest first, so the thread reads top to bottom like a conversation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select u.id, u.body, e.canonical_name, u.created_at
            from updates u left join entities e on e.id = u.author_id
            where u.kind = %s and u.item_id = %s
            order by u.created_at, u.id
            """,
            (kind, item_id),
        )
        return [Update(*r) for r in cur.fetchall()]


def counts(conn: psycopg.Connection, kind: str, item_ids: list[str]) -> dict[str, int]:
    if not item_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "select item_id, count(*) from updates where kind = %s and item_id = any(%s::uuid[]) "
            "group by item_id",
            (kind, item_ids),
        )
        return {str(i): n for i, n in cur.fetchall()}


# --------------------------------------------------------------------------
# the bell


def unread_count(conn: psycopg.Connection, recipient_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("select count(*) from notifications where recipient_id = %s and read_at is null",
                    (recipient_id,))
        return cur.fetchone()[0]


def inbox(conn: psycopg.Connection, recipient_id: str, limit: int = 60) -> list[Notification]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, kind, body, url, created_at, read_at is not null
            from notifications where recipient_id = %s
            order by created_at desc, id desc limit %s
            """,
            (recipient_id, limit),
        )
        return [Notification(*r) for r in cur.fetchall()]


def mark_item_read(conn: psycopg.Connection, recipient_id: str, kind: str, item_id: str) -> None:
    """Opening a task or a lead is reading everything about it."""
    with conn.cursor() as cur:
        cur.execute(
            "update notifications set read_at = now() "
            "where recipient_id = %s and item_kind = %s and item_id = %s and read_at is null",
            (recipient_id, kind, item_id),
        )


def mark_all_read(conn: psycopg.Connection, recipient_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("update notifications set read_at = now() where recipient_id = %s and read_at is null",
                    (recipient_id,))
