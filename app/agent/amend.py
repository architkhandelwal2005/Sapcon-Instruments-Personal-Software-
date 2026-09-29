"""Changing what a meeting recorded, from a reply on WhatsApp.

Until now a reply could only add. "That task is wrong, drop it" appended the
sentence to the transcript and left the wrong task exactly where it was, plus a
new row saying he wanted it gone. The one moment he is actually reading what
the system understood was the one moment he could not fix it.

The safety rule is the same as everywhere else here: the model never picks a
record. The meeting's own items are handed to it with references - T1, C2, D1 -
and it must answer in those references. A reference it invents is dropped, so
the worst a bad answer can do is nothing. What it may change is a closed list,
and none of it destroys: removing an item marks it rejected, the same as
rejecting it on the review screen, and it can be restored there.

Anything that is not one of these changes falls through to being appended,
which is what used to happen to everything. So a reply can still only gain
capability, never lose what he said.
"""

from dataclasses import dataclass
from typing import Optional

import psycopg

from app.llm import complete_json

# What a reference points at, and the table behind it.
_KINDS = {"T": ("task", "tasks"), "C": ("relation", "relations"),
          "D": ("decision", "decisions")}

OPS = {"remove", "retext", "redate", "reassign"}


@dataclass
class Item:
    ref: str
    kind: str
    row_id: str
    text: str


@dataclass
class Amendment:
    op: str
    ref: str
    value: str = ""


def meeting_items(conn: psycopg.Connection, meeting_id: str) -> list:
    """Everything this meeting recorded that a correction could be about."""
    items = []
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.description, t.due_date,
                   coalesce(string_agg(coalesce(e.canonical_name, a.name), ', '), '')
            from tasks t
            left join task_assignees a on a.task_id = t.id
            left join entities e on e.id = a.employee_id
            where t.meeting_id = %s and t.review_status <> 'rejected'
            group by t.id, t.description, t.due_date
            order by t.id
            """,
            (meeting_id,),
        )
        for n, (tid, desc, due, owners) in enumerate(cur.fetchall(), start=1):
            detail = f"{desc} (owner: {owners or 'nobody'}, due: {due or 'none'})"
            items.append(Item(f"T{n}", "task", str(tid), detail))

        cur.execute(
            """
            select r.id, coalesce(r.description, ''), s.canonical_name, g.canonical_name
            from relations r
            left join entities s on s.id = r.source_id
            left join entities g on g.id = r.target_id
            where r.meeting_id = %s and r.review_status <> 'rejected'
            order by r.id
            """,
            (meeting_id,),
        )
        for n, (rid, desc, src, tgt) in enumerate(cur.fetchall(), start=1):
            items.append(Item(f"C{n}", "relation", str(rid),
                              desc or f"{src or '?'} - {tgt or '?'}"))

        cur.execute(
            "select id, description from decisions "
            "where meeting_id = %s and review_status <> 'rejected' order by id",
            (meeting_id,),
        )
        for n, (did, desc) in enumerate(cur.fetchall(), start=1):
            items.append(Item(f"D{n}", "decision", str(did), desc))
    conn.rollback()
    return items


_SYSTEM = """A salesperson recorded a visit by voice note. The system read back what it
understood, and he has replied. Decide whether his reply changes any of the items below,
and how.

Items (refer to them ONLY by these references):
{items}

His reply:
{reply}

Changes you may make:
- {{"op": "remove", "ref": "T2"}} - that item is wrong and should not be there
- {{"op": "retext", "ref": "T1", "value": "the corrected wording"}} - it says the wrong thing
- {{"op": "redate", "ref": "T1", "value": "2026-10-03"}} - the due date is wrong
- {{"op": "reassign", "ref": "T1", "value": "Vishal"}} - the wrong person owns it,
  or nobody does. Use "nobody" to take the owner off.

Return {{"changes": [ ... ]}} - an empty list when his reply adds new information rather
than correcting what is listed, or when you cannot tell which item he means.

Rules:
- Only use a reference from the list above. Never invent one.
- If he is telling you something NEW - another person he met, another thing to do -
  that is not a change. Return an empty list and it will be added separately.
- If he says a name is spelled wrong, that is handled elsewhere. Empty list.
- When two items could be the one he means, return an empty list rather than guessing.
- Dates: today is {today}. Return them as YYYY-MM-DD."""


def plan_amendments(reply: str, items: list, today: str) -> list:
    """What his reply changes. Never raises: no answer means no change, and the
    reply is appended instead, which is what used to happen to all of them."""
    if not items or not (reply or "").strip():
        return []
    listing = "\n".join(f"{i.ref}: {i.text}" for i in items)
    prompt = _SYSTEM.format(items=listing, reply=reply.strip(), today=today)
    try:
        raw = complete_json(prompt, reply.strip(), max_tokens=500)
    except Exception:
        return []
    if isinstance(raw, list):
        raw = {"changes": raw}
    if not isinstance(raw, dict):
        return []

    known = {i.ref for i in items}
    out = []
    for change in raw.get("changes") or []:
        if not isinstance(change, dict):
            continue
        op = str(change.get("op") or "").strip().lower()
        ref = str(change.get("ref") or "").strip().upper()
        # A reference the model made up points at nothing, so it does nothing.
        if op not in OPS or ref not in known:
            continue
        value = str(change.get("value") or "").strip()
        if op in ("retext", "redate", "reassign") and not value:
            continue
        out.append(Amendment(op=op, ref=ref, value=value))
    return out


def apply_amendments(conn: psycopg.Connection, amendments: list, items: list,
                     *, actor_id: Optional[str] = None) -> list:
    """Carry them out. Returns a line of plain English per change made."""
    from app.entity_resolution.employees import find_employee_by_spoken_name

    by_ref = {i.ref: i for i in items}
    done = []
    for change in amendments:
        item = by_ref.get(change.ref)
        if item is None:
            continue
        if change.op == "remove":
            _set_status(conn, item, "rejected", actor_id, "removed from the WhatsApp read-back")
            done.append(f"removed \"{_short(item.text)}\"")
        elif change.op == "retext":
            _update(conn, item, "description", change.value)
            done.append(f"changed it to \"{_short(change.value)}\"")
        elif change.op == "redate" and item.kind == "task":
            _update(conn, item, "due_date", change.value)
            done.append(f"due date for \"{_short(item.text)}\" is now {change.value}")
        elif change.op == "reassign" and item.kind == "task":
            done.append(_reassign(conn, item, change.value, find_employee_by_spoken_name))
    conn.commit()
    return [d for d in done if d]


def _short(text: str, limit: int = 45) -> str:
    text = (text or "").split(" (owner:")[0].strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _table(item: Item) -> str:
    return {"task": "tasks", "relation": "relations", "decision": "decisions"}[item.kind]


def _update(conn: psycopg.Connection, item: Item, column: str, value) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"update {_table(item)} set {column} = %s where id = %s",  # column is ours, not his
            (value or None, item.row_id),
        )


def _set_status(conn: psycopg.Connection, item: Item, status: str,
                actor_id: Optional[str], note: str) -> None:
    """Rejected, not deleted - the same state the review screen sets, and
    restorable from there."""
    with conn.cursor() as cur:
        cur.execute(f"update {_table(item)} set review_status = %s where id = %s",
                    (status, item.row_id))
        try:
            cur.execute(
                "insert into review_decisions (kind, item_id, decision, decided_by, note) "
                "values (%s, %s, 'reject', %s, %s)",
                (item.kind, item.row_id, actor_id, note),
            )
        except Exception:
            pass


def _reassign(conn: psycopg.Connection, item: Item, who: str, lookup) -> str:
    if who.lower() in ("nobody", "no one", "none", "unassigned"):
        with conn.cursor() as cur:
            cur.execute("delete from task_assignees where task_id = %s", (item.row_id,))
        return f"\"{_short(item.text)}\" has no owner now"

    employee = lookup(conn, who)
    if employee is None:
        # Never invent an owner. Saying so is more use than a silent no-op.
        return f"nobody on the team matches \"{who}\", so I left the owner alone"
    employee_id, name = employee
    with conn.cursor() as cur:
        cur.execute("delete from task_assignees where task_id = %s", (item.row_id,))
        cur.execute(
            "insert into task_assignees (task_id, name, employee_id) values (%s, %s, %s)",
            (item.row_id, name, employee_id),
        )
    return f"\"{_short(item.text)}\" is now {name}'s"
