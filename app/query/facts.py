"""The records behind an answer, as opposed to the transcripts.

Until now a question was answered only from meeting transcripts, so everything
the pipeline carefully extracted - tasks with owners and due dates, leads and
their status, decisions, phone numbers - was unreachable at query time. "What is
pending with Vishal" could not be answered, and "give me Rajesh's number" could
not either, although the number was sitting in a column.

Each row is rendered as one self-contained line with a short reference like F3,
which the model cites instead of quoting. A transcript claim is testimony and
must be quoted verbatim, because the transcription and the extraction can both
be wrong. A record is the system's own state, so quoting it would only prove
that we printed what we printed; checking that the reference exists is both
stronger and free.

Rows still pending review are included but marked, because 323 diary items are
pending and hiding them would make the answer wrong in the other direction -
but they must never read as settled fact.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import psycopg

# Per kind, so one busy customer cannot crowd out every other sort of record.
PER_KIND = 15
STALE_LEAD_DAYS = 14


@dataclass
class Fact:
    ref: str            # "F3" - what the model cites
    kind: str           # contact | task | lead | relation | decision
    row_id: str
    text: str           # one self-contained line
    url_path: str       # where a person goes to see it
    entity_id: Optional[str] = None


@dataclass
class FactPack:
    facts: list[Fact] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)

    def by_ref(self) -> dict[str, Fact]:
        return {f.ref: f for f in self.facts}

    def __bool__(self) -> bool:
        return bool(self.facts)


def _pending(review_status: Optional[str]) -> str:
    return " [unreviewed]" if review_status == "pending" else ""


def _due(due_date: Optional[date]) -> str:
    return due_date.strftime("%d %b %Y") if due_date else "no due date"


def contact_facts(conn: psycopg.Connection, entity_id: str) -> list[dict]:
    """The contact card: the answer to "what is his number"."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, canonical_name, entity_type, title, phone, email, region,
                   source, first_seen, review_status
            from entities where id = %s
            """,
            (entity_id,),
        )
        row = cur.fetchone()
    if row is None:
        return []
    eid, name, etype, title, phone, email, region, source, first_seen, review_status = row
    bits = [f"{name} ({etype})"]
    for label, value in (("title", title), ("phone", phone), ("email", email), ("region", region)):
        if value:
            bits.append(f"{label} {value}")
    if first_seen:
        bits.append(f"first seen {first_seen}")
    return [{
        "kind": "contact", "row_id": str(eid), "entity_id": str(eid),
        "url_path": f"/entities/{eid}",
        "text": "Contact card: " + ", ".join(bits) + _pending(review_status),
    }]


def task_facts(conn: psycopg.Connection, entity_id: str, limit: int = PER_KIND) -> list[dict]:
    """Tasks this entity owns and tasks about it - "what is pending with Vishal"
    means either sense, and the asker does not distinguish."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.id, t.description, t.due_date, t.status, t.review_status,
                   re.canonical_name,
                   coalesce(string_agg(distinct coalesce(oe.canonical_name, ta.name), ', '), '') as owners,
                   bool_or(ta.employee_id = %(e)s) as is_owner
            from tasks t
            left join entities re on re.id = t.related_entity_id
            left join task_assignees ta on ta.task_id = t.id
            left join entities oe on oe.id = ta.employee_id
            where t.review_status <> 'rejected'
              and (t.related_entity_id = %(e)s
                   or exists (select 1 from task_assignees x
                              where x.task_id = t.id and x.employee_id = %(e)s))
            group by t.id, t.description, t.due_date, t.status, t.review_status, re.canonical_name
            order by (t.status = 'open') desc, t.due_date nulls last
            limit %(n)s
            """,
            {"e": entity_id, "n": limit},
        )
        rows = cur.fetchall()

    out = []
    for tid, desc, due, status, review_status, about, owners, is_owner in rows:
        parts = [f"Task ({status}): {desc}", f"owner {owners or 'nobody'}", _due(due)]
        if about:
            parts.append(f"about {about}")
        out.append({
            "kind": "task", "row_id": str(tid), "entity_id": entity_id,
            "url_path": "/tasks",
            "text": " -- ".join(parts) + _pending(review_status),
        })
    return out


def lead_facts(conn: psycopg.Connection, entity_id: str, limit: int = PER_KIND) -> list[dict]:
    """Leads this entity is, and leads allotted to it when it is a staff member."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select l.id, e.canonical_name, l.status, l.source, l.next_follow_up_due,
                   l.notes, ae.canonical_name, l.created_at,
                   (select max(m.meeting_date) from meetings m where m.id in (
                        select meeting_id from relations
                        where (source_id = l.entity_id or target_id = l.entity_id)
                          and review_status <> 'rejected'
                        union
                        select meeting_id from tasks
                        where related_entity_id = l.entity_id and review_status <> 'rejected'
                   )) as last_activity
            from leads l
            join entities e on e.id = l.entity_id
            left join entities ae on ae.id = l.assigned_to
            where l.entity_id = %(e)s or l.assigned_to = %(e)s
            order by l.next_follow_up_due nulls last, l.created_at desc
            limit %(n)s
            """,
            {"e": entity_id, "n": limit},
        )
        rows = cur.fetchall()

    today = date.today()
    out = []
    for lid, name, status, source, due, notes, owner, created_at, last_activity in rows:
        parts = [f"Lead: {name}", f"status {status}", f"allotted to {owner or 'nobody'}"]
        if source:
            parts.append(f"from {source}")
        if due:
            parts.append(f"follow up {due.strftime('%d %b %Y')}")
        last = last_activity or (created_at.date() if created_at else None)
        if status == "open" and last and (today - last).days >= STALE_LEAD_DAYS:
            parts.append(f"no activity for {(today - last).days} days")
        elif last_activity:
            parts.append(f"last activity {last_activity.strftime('%d %b %Y')}")
        if notes:
            parts.append(f"notes: {notes[:120]}")
        out.append({
            "kind": "lead", "row_id": str(lid), "entity_id": entity_id,
            "url_path": f"/leads/{lid}", "text": " -- ".join(parts),
        })
    return out


def relation_facts(conn: psycopg.Connection, entity_id: str, limit: int = PER_KIND) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select r.id, r.description, r.role_tag, r.provenance, r.review_status,
                   se.canonical_name, te.canonical_name
            from relations r
            join entities se on se.id = r.source_id
            join entities te on te.id = r.target_id
            where (r.source_id = %(e)s or r.target_id = %(e)s)
              and r.review_status <> 'rejected' and r.status = 'active'
            order by (r.review_status = 'pending'), r.recorded_at desc
            limit %(n)s
            """,
            {"e": entity_id, "n": limit},
        )
        rows = cur.fetchall()
    return [{
        "kind": "relation", "row_id": str(rid), "entity_id": entity_id,
        "url_path": f"/entities/{entity_id}",
        "text": f"Connection: {desc or f'{src} - {tgt}'}"
                + (f" ({role})" if role else "")
                + (" [heard second-hand]" if provenance == "hearsay" else "")
                + _pending(review_status),
    } for rid, desc, role, provenance, review_status, src, tgt in rows]


def decision_facts(conn: psycopg.Connection, entity_id: str, limit: int = PER_KIND) -> list[dict]:
    """Decisions from internal meetings this person attended - targets,
    rankings, who owns what."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select d.id, d.description, d.review_status, m.meeting_date, m.id
            from decisions d
            join meetings m on m.id = d.meeting_id
            where d.review_status <> 'rejected'
              and exists (select 1 from meeting_attendees a
                          where a.meeting_id = m.id and a.employee_id = %(e)s)
            order by m.meeting_date desc
            limit %(n)s
            """,
            {"e": entity_id, "n": limit},
        )
        rows = cur.fetchall()
    return [{
        "kind": "decision", "row_id": str(did), "entity_id": entity_id,
        "url_path": f"/meetings/{mid}",
        "text": f"Decision ({mdate.strftime('%d %b %Y')}): {desc}" + _pending(review_status),
    } for did, desc, review_status, mdate, mid in rows]


def entity_facts(conn: psycopg.Connection, entity_id: str, *, per_kind: int = PER_KIND) -> list[dict]:
    return (
        contact_facts(conn, entity_id)
        + task_facts(conn, entity_id, per_kind)
        + lead_facts(conn, entity_id, per_kind)
        + relation_facts(conn, entity_id, per_kind)
        + decision_facts(conn, entity_id, per_kind)
    )


# Questions with no name in them - "what is overdue", "which leads are stale".
# Deliberately keyword-gated rather than routed by a model: a planner would cost
# another call against a 500-a-day quota and could silently decide not to look.
_OVERDUE = ("overdue", "late", "due", "pending", "outstanding")
_STALE = ("stale", "untouched", "no activity", "forgotten", "cold")
_UNASSIGNED = ("unassigned", "unallotted", "nobody", "no owner", "allot")


def global_facts(conn: psycopg.Connection, question: str, *, per_kind: int = 20) -> list[dict]:
    q = (question or "").lower()
    out: list[dict] = []

    if any(w in q for w in _OVERDUE):
        with conn.cursor() as cur:
            cur.execute(
                """
                select t.id, t.description, t.due_date, t.review_status,
                       coalesce(string_agg(distinct coalesce(oe.canonical_name, ta.name), ', '), '') as owners,
                       re.canonical_name
                from tasks t
                left join task_assignees ta on ta.task_id = t.id
                left join entities oe on oe.id = ta.employee_id
                left join entities re on re.id = t.related_entity_id
                where t.status = 'open' and t.review_status <> 'rejected'
                group by t.id, t.description, t.due_date, t.review_status, re.canonical_name
                order by t.due_date nulls last
                limit %(n)s
                """,
                {"n": per_kind},
            )
            for tid, desc, due, review_status, owners, about in cur.fetchall():
                parts = [f"Open task: {desc}", f"owner {owners or 'nobody'}", _due(due)]
                if about:
                    parts.append(f"about {about}")
                out.append({"kind": "task", "row_id": str(tid), "entity_id": None,
                            "url_path": "/tasks", "text": " -- ".join(parts) + _pending(review_status)})

    if any(w in q for w in _STALE) or any(w in q for w in _UNASSIGNED):
        unassigned_only = any(w in q for w in _UNASSIGNED) and not any(w in q for w in _STALE)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select l.id, e.canonical_name, l.status, ae.canonical_name, l.next_follow_up_due,
                       l.created_at
                from leads l
                join entities e on e.id = l.entity_id
                left join entities ae on ae.id = l.assigned_to
                where l.status = 'open' {"and l.assigned_to is null" if unassigned_only else ""}
                order by l.next_follow_up_due nulls last, l.created_at
                limit %(n)s
                """,
                {"n": per_kind},
            )
            for lid, name, status, owner, due, created_at in cur.fetchall():
                parts = [f"Lead: {name}", f"status {status}", f"allotted to {owner or 'nobody'}"]
                if due:
                    parts.append(f"follow up {due.strftime('%d %b %Y')}")
                out.append({"kind": "lead", "row_id": str(lid), "entity_id": None,
                            "url_path": f"/leads/{lid}", "text": " -- ".join(parts)})
    return out


def build_fact_pack(
    conn: psycopg.Connection,
    entity_ids: list[str],
    question: str,
    *,
    max_chars: int,
) -> FactPack:
    """Records for the entities named in the question, or a keyword-gated slice
    when no name was recognised. Trimmed to a character budget, counting what
    was left out so the answer can admit it."""
    raw: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entity_id in entity_ids:
        for row in entity_facts(conn, entity_id):
            key = (row["kind"], row["row_id"])
            if key not in seen:
                seen.add(key)
                raw.append(row)
    if not entity_ids:
        raw = global_facts(conn, question)

    pack = FactPack()
    used = 0
    for i, row in enumerate(raw, start=1):
        line_cost = len(row["text"]) + 8
        if used + line_cost > max_chars:
            pack.dropped[row["kind"]] = pack.dropped.get(row["kind"], 0) + 1
            continue
        used += line_cost
        pack.facts.append(Fact(ref=f"F{i}", kind=row["kind"], row_id=row["row_id"],
                               text=row["text"], url_path=row["url_path"],
                               entity_id=row.get("entity_id")))
    return pack


def render_fact_pack(pack: FactPack) -> str:
    if not pack.facts:
        return ""
    lines = [f"[{f.ref}] {f.text}" for f in pack.facts]
    if pack.dropped:
        left_out = ", ".join(f"{n} more {kind}(s)" for kind, n in sorted(pack.dropped.items()))
        lines.append(f"(not shown for space: {left_out})")
    return "\n".join(lines)
