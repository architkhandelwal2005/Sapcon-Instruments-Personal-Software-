"""Once-a-day jobs, run from the background loop in app/mailer.py.

- 09:00 IST: each employee gets one email - what is due today, what is late,
  which of their leads have gone quiet. Nothing to say, no email.
- 09:00 IST: a task three or more days late is reported to the owner and the
  office, once per task. The owner reads it in "updates" on WhatsApp.

Each job claims its day in daily_runs before doing anything, so a restart, a
redeploy or a second copy of the app cannot run it twice.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg

from app import mailer
from app.web.routes.leads import STALE_AFTER_DAYS, _search as search_leads

IST = timezone(timedelta(hours=5, minutes=30))
MORNING_HOUR = 9
ESCALATE_AFTER_DAYS = 3
MAX_LINES = 12


def _today_ist(now: datetime | None = None) -> tuple[date, int]:
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    return now.date(), now.hour


def _claim(conn: psycopg.Connection, job: str, day: date) -> bool:
    with conn.cursor() as cur:
        cur.execute("insert into daily_runs (job, day) values (%s, %s) on conflict do nothing", (job, day))
        claimed = cur.rowcount == 1
    conn.commit()
    return claimed


def run_due(conn: psycopg.Connection, base_url: str, now: datetime | None = None) -> None:
    day, hour = _today_ist(now)
    if hour < MORNING_HOUR:
        return
    if _claim(conn, "overdue_escalation", day):
        escalate_overdue(conn)
        conn.commit()
    if mailer.configured() and _claim(conn, "morning_email", day):
        sent = morning_emails(conn, base_url, day)
        print(f"daily: sent {sent} morning emails")


def escalate_overdue(conn: psycopg.Connection) -> int:
    """Tell the owner and the office about work that is badly late."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into notifications (recipient_id, kind, item_kind, item_id, body, url)
            select u.entity_id, 'overdue', 'task', t.id,
                   coalesce(string_agg(distinct coalesce(e.canonical_name, ta.name), ', '), 'Nobody')
                     || ' - ' || (current_date - t.due_date) || ' days late: '
                     || left(t.description, 140),
                   '/tasks/' || t.id
            from tasks t
            left join task_assignees ta on ta.task_id = t.id
            left join entities e on e.id = ta.employee_id
            cross join app_users u
            where t.status <> 'done' and t.review_status <> 'rejected'
              and t.due_date <= current_date - %s
              and u.role in ('owner', 'office') and not u.disabled
            group by u.entity_id, t.id
            on conflict do nothing
            """,
            (ESCALATE_AFTER_DAYS,),
        )
        return cur.rowcount


def _employee_lines(conn: psycopg.Connection, day: date) -> dict[str, dict]:
    """Per employee with an email address: today's tasks, late tasks, quiet leads."""
    people: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            select e.id, e.canonical_name, e.email from entities e
            join app_users u on u.entity_id = e.id
            where u.role = 'employee' and not u.disabled and coalesce(e.email, '') like '%%@%%'
              and not exists (select 1 from whatsapp_senders ws where ws.entity_id = e.id)
            """
        )
        for eid, name, email in cur.fetchall():
            people[str(eid)] = {"name": name, "email": email.strip(), "today": [], "late": [], "quiet": []}
        cur.execute(
            """
            select ta.employee_id, t.id, t.description, t.due_date
            from tasks t join task_assignees ta on ta.task_id = t.id
            where t.status <> 'done' and t.review_status <> 'rejected' and t.due_date <= %s
            order by t.due_date
            """,
            (day,),
        )
        for eid, tid, desc, due in cur.fetchall():
            p = people.get(str(eid))
            if p is None:
                continue
            if due == day:
                p["today"].append((desc, f"/tasks/{tid}"))
            else:
                p["late"].append((f"{desc} ({(day - due).days} days late)", f"/tasks/{tid}"))
    for lead in search_leads(conn, "l.status = 'open'", {}):
        p = people.get(lead["assigned_to"] or "")
        if p is not None and lead["stale"]:
            p["quiet"].append((lead["canonical_name"], f"/leads/{lead['id']}"))
    return people


def morning_email(name: str, today: list, late: list, quiet: list, base_url: str) -> mailer.Digest | None:
    """One person's morning email, or None when there is nothing to say."""
    if not (today or late or quiet):
        return None
    sections = []
    if late:
        sections.append(("Late", late))
    if today:
        sections.append(("Due today", today))
    if quiet:
        sections.append((f"Leads with no activity for {STALE_AFTER_DAYS}+ days", quiet))
    first = name.split()[0] if name else "there"
    counts = [f"{len(late)} late" if late else "", f"{len(today)} due today" if today else "",
              f"{len(quiet)} quiet leads" if quiet else ""]
    subject = "Your work today: " + ", ".join(c for c in counts if c)

    text = [f"Good morning {first},", ""]
    html_parts = [f"<p>Good morning {mailer.html.escape(first)},</p>"]
    for title, items in sections:
        shown = items[:MAX_LINES]
        text.append(title.upper())
        text += [f"- {label}\n  {base_url}{path}" for label, path in shown]
        rows = "".join(
            f'<li style="margin:0 0 8px"><a href="{mailer.html.escape(base_url + path)}" '
            f'style="color:#1a5f3f;text-decoration:none">{mailer.html.escape(label)}</a></li>'
            for label, path in shown)
        more = len(items) - len(shown)
        if more:
            text.append(f"  +{more} more")
            rows += f"<li>+{more} more</li>"
        text.append("")
        html_parts.append(f"<h3 style=\"margin:16px 0 6px\">{mailer.html.escape(title)}</h3>"
                          f"<ul style=\"padding-left:18px\">{rows}</ul>")
    text.append(f"Your tasks: {base_url}/tasks")
    html_parts.append(f'<p><a href="{base_url}/tasks" style="color:#1a5f3f">Open your tasks</a></p>')
    html = '<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a">' + "".join(html_parts) + "</div>"
    return mailer.Digest(subject, "\n".join(text), html)


def morning_emails(conn: psycopg.Connection, base_url: str, day: date, sender=None) -> int:
    sender = sender or mailer.send
    sent = 0
    for p in _employee_lines(conn, day).values():
        digest = morning_email(p["name"], p["today"], p["late"], p["quiet"], base_url)
        if digest is None:
            continue
        try:
            sender(p["email"], p["name"], digest)
            sent += 1
        except Exception as exc:
            print(f"daily: morning email to {p['name']} failed: {exc}", file=sys.stderr)
    return sent
