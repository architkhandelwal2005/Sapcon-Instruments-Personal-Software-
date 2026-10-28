"""Every hand edit, who made it, what it was before - and the way back.

One place owns changing a field, because three things have to happen together
and happen identically whether the change came from the website or from a
WhatsApp instruction: read the current value, write the new one, and record
both. Undo is the same thing in reverse, so it lives here too.

Undo writes the recorded previous value back, but only if the field still holds
what this change set. If somebody has changed it again since, undoing the older
change would quietly overwrite theirs - so that is refused, and the person is
told why. The read takes a row lock, so two people editing the same task at the
same moment are put in order rather than racing, and each change records the
value it actually replaced.

Nothing here commits. A form that changes three fields commits once, so the
three changes land together or not at all.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import psycopg

# Contact fields a person may correct by hand. The same list decides what the
# edit form offers and what this module will write, so neither can drift.
CONTACT_FIELDS = ("canonical_name", "phone", "email", "title", "region")
LEAD_FIELDS = ("status", "next_follow_up_due", "notes", "order_value", "drop_reason")

FIELD_LABELS = {
    "canonical_name": "name", "phone": "phone", "email": "email", "title": "title",
    "region": "region", "status": "status", "next_follow_up_due": "follow-up date",
    "notes": "notes", "owners": "owner", "order_value": "order value",
    "drop_reason": "reason for dropping",
}

_MISSING = object()


@dataclass
class Change:
    id: int
    kind: str
    item_id: str
    field: str
    before: Any
    after: Any
    changed_by: Optional[str]
    changed_by_name: Optional[str]
    changed_at: datetime
    via: str
    undone_at: Optional[datetime]
    undone_by_name: Optional[str]

    @property
    def is_undone(self) -> bool:
        return self.undone_at is not None

    def describe(self) -> str:
        return describe(self.kind, self.field, self.before, self.after)


# --------------------------------------------------------------------------
# reading and writing one field


def _plain(value):
    """What is stored and compared. Dates become text so a value read back from
    jsonb compares equal to the one that went in."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        # numeric comes back as Decimal('50000.00'); stored and compared as
        # plain text so "50000" typed in a form is the same amount.
        return format(value.normalize(), "f")
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _read(conn, kind: str, item_id: str, field: str):
    """The current value, with the row locked until the transaction ends."""
    with conn.cursor() as cur:
        if kind == "task" and field == "status":
            cur.execute("select status from tasks where id = %s for update", (item_id,))
        elif kind == "task" and field == "owners":
            cur.execute("select 1 from tasks where id = %s for update", (item_id,))
            if cur.fetchone() is None:
                return _MISSING
            cur.execute(
                "select coalesce(employee_id::text, ''), name from task_assignees "
                "where task_id = %s order by name",
                (item_id,),
            )
            return [{"employee_id": eid or None, "name": name} for eid, name in cur.fetchall()]
        elif kind == "lead" and field in LEAD_FIELDS:
            cur.execute(f"select {field} from leads where id = %s for update", (item_id,))
        elif kind == "contact" and field in CONTACT_FIELDS:
            cur.execute(f"select {field} from entities where id = %s for update", (item_id,))
        else:
            raise ValueError(f"no such editable field: {kind}.{field}")
        row = cur.fetchone()
    return _MISSING if row is None else _plain(row[0])


def _write(conn, kind: str, item_id: str, field: str, value, actor_id: Optional[str]) -> None:
    with conn.cursor() as cur:
        if kind == "task" and field == "status":
            cur.execute("update tasks set status = %s where id = %s", (value, item_id))
        elif kind == "task" and field == "owners":
            cur.execute("delete from task_assignees where task_id = %s", (item_id,))
            for owner in value or []:
                cur.execute(
                    "insert into task_assignees (task_id, name, employee_id) values (%s, %s, %s)",
                    (item_id, owner["name"], owner.get("employee_id")),
                )
        elif kind == "lead" and field == "status":
            cur.execute(
                "update leads set status = %s, status_changed_at = now(), status_changed_by = %s "
                "where id = %s",
                (value, actor_id, item_id),
            )
        elif kind == "lead" and field in LEAD_FIELDS:
            cur.execute(f"update leads set {field} = %s where id = %s", (value, item_id))
        elif kind == "contact" and field in CONTACT_FIELDS:
            cur.execute(f"update entities set {field} = %s where id = %s", (value, item_id))
        else:
            raise ValueError(f"no such editable field: {kind}.{field}")


def _same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        # Owners are the same people when they are the same staff records. A
        # name is only a fallback for an owner never matched to the roster:
        # "Vishal" heard on a call and "Vishal Dixit" picked from a list are one
        # person, and recording a change between them would be noise.
        key = lambda o: o.get("employee_id") or (o.get("name") or "").strip().lower()
        return sorted(map(key, a)) == sorted(map(key, b))
    return a == b


# --------------------------------------------------------------------------
# the three things callers do


def change(conn: psycopg.Connection, kind: str, item_id: str, field: str, new, *,
           actor_id: Optional[str], via: str = "website") -> Optional[int]:
    """Set one field and record it. Returns the change id, or None when the
    row does not exist or already held this value. Does not commit."""
    new = _plain(new) if not isinstance(new, list) else new
    old = _read(conn, kind, item_id, field)
    if old is _MISSING or _same(old, new):
        return None

    _write(conn, kind, item_id, field, new, actor_id)

    if kind == "contact" and field == "canonical_name" and old:
        # The old spelling stays findable. Voice notes reach a contact by the
        # name that was said, and a correction should not orphan every later
        # mention of the spelling it corrected.
        with conn.cursor() as cur:
            cur.execute(
                "update entities set aliases = array_append(coalesce(aliases, '{}'), %s) "
                "where id = %s and not (%s = any(coalesce(aliases, '{}')))",
                (old, item_id, old),
            )

    with conn.cursor() as cur:
        cur.execute(
            "insert into change_log (kind, item_id, field, before, after, changed_by, via) "
            "values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s) returning id",
            (kind, item_id, field, json.dumps(old), json.dumps(new), actor_id, via),
        )
        return cur.fetchone()[0]


# What an undo attempt came to, in words. One table, read by the website's
# undo bar and by the WhatsApp reply, so the two can never say different things.
UNDO_WORDS = {
    "done": "Undone.",
    "changed": "Not undone - it has been changed again since, and undoing would overwrite that.",
    "notyours": "Not undone - only the person who made that change can undo it.",
    "already": "That was already undone.",
    "missing": "Not undone - that item no longer exists.",
}


def undo(conn: psycopg.Connection, change_id: int, *, actor_id: Optional[str],
         may_undo_others: bool) -> str:
    """Put one field back. Returns a key of UNDO_WORDS. Does not commit.

    Refused when it has already been undone, when it was somebody else's and
    the person asking may only undo their own, and when the field has changed
    again since - undoing then would overwrite the later change, not this one.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select kind, item_id, field, before, after, changed_by, undone_at "
            "from change_log where id = %s for update",
            (change_id,),
        )
        row = cur.fetchone()
    if row is None:
        return "missing"
    kind, item_id, field, before, after, changed_by, undone_at = row
    item_id, changed_by = str(item_id), (str(changed_by) if changed_by else None)

    if undone_at is not None:
        return "already"
    if not may_undo_others and changed_by != actor_id:
        return "notyours"

    current = _read(conn, kind, item_id, field)
    if current is _MISSING:
        return "missing"
    if not _same(current, after):
        return "changed"

    _write(conn, kind, item_id, field, before, actor_id)
    with conn.cursor() as cur:
        cur.execute(
            "update change_log set undone_at = now(), undone_by = %s where id = %s",
            (actor_id, change_id),
        )
    return "done"


def recent(conn: psycopg.Connection, kind: str, item_id: str, limit: int = 8) -> list[Change]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select c.id, c.kind, c.item_id, c.field, c.before, c.after, c.changed_by,
                   b.canonical_name, c.changed_at, c.via, c.undone_at, u.canonical_name
            from change_log c
            left join entities b on b.id = c.changed_by
            left join entities u on u.id = c.undone_by
            where c.kind = %s and c.item_id = %s
            order by c.changed_at desc, c.id desc
            limit %s
            """,
            (kind, item_id, limit),
        )
        rows = cur.fetchall()
    return [
        Change(r[0], r[1], str(r[2]), r[3], r[4], r[5], str(r[6]) if r[6] else None,
               r[7], r[8], r[9], r[10], r[11])
        for r in rows
    ]


# --------------------------------------------------------------------------
# words


def _show(value) -> str:
    if value is None or value == "":
        return "nothing"
    if isinstance(value, list):
        return ", ".join(o["name"] for o in value) or "nobody"
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return date.fromisoformat(value).strftime("%d %b")
        except ValueError:
            pass
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def describe(kind: str, field: str, before, after) -> str:
    """One short line a person reads in a list of changes."""
    if kind == "task" and field == "status":
        return "marked done" if after == "done" else "reopened"
    if field == "owners":
        if not after:
            return "took the owner off"
        return f"gave it to {_show(after)}"
    if field == "notes":
        return "edited the notes"
    label = FIELD_LABELS.get(field, field)
    if before in (None, ""):
        return f"set {label} to {_show(after)}"
    return f"changed {label} from {_show(before)} to {_show(after)}"


def ago(when: datetime) -> str:
    """'just now', '5 min ago', '3 h ago', '12 Oct'."""
    now = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (now - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return when.strftime("%d %b")
