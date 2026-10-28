"""What has happened since he last asked - the owner's notifications, on WhatsApp.

The owner hears everything on WhatsApp, but the CRM may only write to him
inside the 24 hours after he last wrote to it, unless it uses a template Meta
has approved - and templates need a registered business number. So the news
waits behind "updates": he asks, and the reply is free and always allowed.
Every other reply to him ends with a one-line count, so he knows when it is
worth asking.
"""

from datetime import date
from typing import Optional

import psycopg

from app.web.routes.leads import STALE_AFTER_DAYS, _search as search_leads

# Typed or said on their own, these ask for the digest. Matched before the
# model is asked anything, so the commonest request costs no AI call.
TRIGGERS = {
    "updates", "update", "any updates", "any update", "summary", "report",
    "whats new", "what's new", "news", "kya update", "kya update hai", "status update",
}
MAX_ITEMS = 15


def wants_updates(text: str) -> bool:
    words = " ".join((text or "").lower().replace("?", " ").replace("!", " ").split())
    return words in TRIGGERS


def unread_count(conn: psycopg.Connection, entity_id: Optional[str]) -> int:
    if not entity_id:
        return 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from notifications where recipient_id = %s and read_at is null",
                    (entity_id,))
        return cur.fetchone()[0]


def nudge(conn: psycopg.Connection, entity_id: Optional[str]) -> str:
    n = unread_count(conn, entity_id)
    if not n:
        return ""
    return f"\n\n{n} new update{'s' if n != 1 else ''} from the team - send \"updates\" to see them."


def _team_lines(conn: psycopg.Connection) -> list[str]:
    """Where the work stands today, in a few lines."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select coalesce(e.canonical_name, ta.name), count(*)
            from tasks t join task_assignees ta on ta.task_id = t.id
            left join entities e on e.id = ta.employee_id
            where t.status <> 'done' and t.review_status <> 'rejected'
              and t.due_date < current_date
            group by 1 order by 2 desc, 1 limit 6
            """
        )
        overdue = cur.fetchall()
        cur.execute(
            """
            select count(distinct item_id) from change_log
            where kind = 'task' and field = 'status' and after = '"done"'::jsonb
              and undone_at is null and changed_at > now() - interval '1 day'
            """
        )
        done_today = cur.fetchone()[0]
    quiet = sum(1 for lead in search_leads(conn, "l.status = 'open'", {}) if lead["stale"])

    lines = [f"Tasks finished in the last 24 hours: {done_today}"]
    if overdue:
        lines.append("Overdue: " + ", ".join(f"{name} {n}" for name, n in overdue))
    else:
        lines.append("Overdue: none")
    lines.append(f"Open leads with no activity for {STALE_AFTER_DAYS}+ days: {quiet}")
    return lines


def updates_reply(conn: psycopg.Connection, entity_id: str, base_url: str) -> str:
    """The reply to "updates". Marks what it shows as read - it has been
    delivered - and does not commit; the caller does, after sending."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, body, url from notifications
            where recipient_id = %s and read_at is null
            order by created_at desc, id desc
            """,
            (entity_id,),
        )
        rows = cur.fetchall()
        if rows:
            cur.execute("update notifications set read_at = now() where id = any(%s)",
                        ([r[0] for r in rows],))

    parts = [f"UPDATES - {date.today():%d %b}"]
    if rows:
        shown = rows[:MAX_ITEMS]
        parts.append("\n".join(f"- {body}" for _, body, _ in shown))
        if len(rows) > MAX_ITEMS:
            parts.append(f"+{len(rows) - MAX_ITEMS} more: {base_url}/notifications")
    else:
        parts.append("Nothing new from the team since you last asked.")
    parts.append("TEAM TODAY\n" + "\n".join(_team_lines(conn)))
    parts.append(f"Everyone's work: {base_url}/team")
    text = "\n\n".join(parts)
    return text if len(text) <= 3900 else text[:3880] + "\n..."
