"""Notifications by email, until WhatsApp can carry them.

A background loop collects each person's unread notifications and sends them as
one email. Waiting a couple of minutes before sending does two things: several
changes made together arrive as one email rather than five, and somebody who is
on the site and reads the notification there is not emailed it as well.

Sending is through Brevo's HTTP API rather than SMTP, because hosts commonly
block outgoing mail ports, and because its free tier needs no card. Without
BREVO_API_KEY nothing is sent and nothing is marked - the notifications stay on
the site, and are emailed once a key is set, as long as they are still unread.
"""

import html
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import psycopg

from app.db import get_connection, release_connection

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
WAIT_MINUTES = 2        # let several changes become one email, and let the site be read first
EVERY_SECONDS = 60
GIVE_UP_DAYS = 3        # an unread notice this old is stale news, not worth an email


@dataclass
class Digest:
    subject: str
    text: str
    html: str


def build_digest(name: str, items: list[tuple[str, str]], base_url: str) -> Digest:
    """One email for one person. `items` is (body, path), newest first."""
    first = name.split()[0] if name else "there"
    if len(items) == 1:
        body = items[0][0]
        subject = body if len(body) <= 90 else body[:87] + "..."
    else:
        subject = f"{len(items)} new notifications - Sapcon CRM"

    lines = [f"Hi {first},", ""]
    lines += [f"- {body}\n  {base_url}{path}" for body, path in items]
    lines += ["", f"All notifications: {base_url}/notifications"]

    rows = "".join(
        f'<li style="margin:0 0 12px"><a href="{html.escape(base_url + path)}" '
        f'style="color:#1a5f3f;text-decoration:none">{html.escape(body)}</a></li>'
        for body, path in items
    )
    page = (
        f'<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a">'
        f"<p>Hi {html.escape(first)},</p><ul style=\"padding-left:18px\">{rows}</ul>"
        f'<p><a href="{html.escape(base_url)}/notifications" style="color:#1a5f3f">'
        f"Open all notifications</a></p></div>"
    )
    return Digest(subject, "\n".join(lines), page)


def send(to_email: str, to_name: str, digest: Digest) -> None:
    """Raises on failure."""
    payload = json.dumps({
        "sender": {"name": os.environ.get("MAIL_FROM_NAME", "Sapcon CRM"),
                   "email": os.environ["MAIL_FROM"]},
        "to": [{"email": to_email, "name": to_name}],
        "subject": digest.subject,
        "textContent": digest.text,
        "htmlContent": digest.html,
    }).encode()
    req = urllib.request.Request(
        BREVO_URL, data=payload, method="POST",
        headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def _pending(conn: psycopg.Connection) -> dict[str, dict]:
    """Unread, unsent notices for people with an email address, grouped by person.
    Rows are locked so a second copy of the app could not send them twice."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select n.id, n.recipient_id, e.canonical_name, e.email, n.body, n.url
            from notifications n
            join entities e on e.id = n.recipient_id
            join app_users u on u.entity_id = n.recipient_id and not u.disabled
            where n.emailed_at is null and n.read_at is null
              -- People who use the CRM on WhatsApp hear from it there; see
              -- app/whatsapp/digest.py. Everyone else hears by email.
              and not exists (select 1 from whatsapp_senders ws where ws.entity_id = n.recipient_id)
              and n.created_at < now() - interval '{WAIT_MINUTES} minutes'
              and n.created_at > now() - interval '{GIVE_UP_DAYS} days'
              and coalesce(e.email, '') like '%%@%%'
            order by n.created_at desc, n.id desc
            for update of n skip locked
            """
        )
        people: dict[str, dict] = {}
        for nid, rid, name, email, body, url in cur.fetchall():
            p = people.setdefault(str(rid), {"name": name, "email": email.strip(), "ids": [], "items": []})
            p["ids"].append(nid)
            p["items"].append((body, url))
    return people


def flush(conn: psycopg.Connection, base_url: str, sender=send) -> int:
    """Send what is due. Returns how many emails went out."""
    sent = 0
    people = _pending(conn)
    for p in people.values():
        try:
            sender(p["email"], p["name"], build_digest(p["name"], p["items"], base_url))
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                # 401/403 is our key or sender, 429 and 5xx are passing: none
                # of them is this person's fault, so keep their notices.
                print(f"email to {p['name']} failed, will retry: {exc}", file=sys.stderr)
                continue
            # A malformed address will not get better. Mark it, so it is not
            # retried every minute; the notices are still on the site.
            print(f"email to {p['name']} refused ({exc.code}), not retrying", file=sys.stderr)
        except Exception as exc:  # network trouble: try again next round
            print(f"email to {p['name']} failed, will retry: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        else:
            sent += 1
        with conn.cursor() as cur:
            cur.execute("update notifications set emailed_at = now() where id = any(%s)", (p["ids"],))
    conn.commit()
    return sent


def _loop(base_url: str) -> None:
    from app import daily

    while True:
        time.sleep(EVERY_SECONDS)
        try:
            conn = get_connection()
        except Exception as exc:
            print(f"mailer: no database connection: {exc}", file=sys.stderr)
            continue
        try:
            daily.run_due(conn, base_url)
            if configured():
                flush(conn, base_url)
        except Exception as exc:
            print(f"mailer: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            release_connection(conn)


def configured() -> bool:
    return bool(os.environ.get("BREVO_API_KEY") and os.environ.get("MAIL_FROM"))


def start() -> bool:
    """Start the background loop. It always runs - the daily overdue check
    needs no email - but sends mail only once email is configured."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        print("mailer: PUBLIC_BASE_URL not set - background jobs not started")
        return False
    if not configured():
        print("mailer: BREVO_API_KEY / MAIL_FROM not set - notifications stay on the site only")
    threading.Thread(target=_loop, args=(base,), name="mailer", daemon=True).start()
    return True
