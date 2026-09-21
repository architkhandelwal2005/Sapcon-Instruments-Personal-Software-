from dataclasses import dataclass
from datetime import date
from typing import Optional

import psycopg


@dataclass
class ConnectionRow:
    source: str
    source_id: str
    target: str
    target_id: str
    description: str
    role_tag: Optional[str]
    provenance: str
    confidence: Optional[str]
    review_status: str
    source_quote: Optional[str]
    relation_id: str


@dataclass
class TaskRow:
    description: str
    related_entity_name: Optional[str]
    related_entity_id: Optional[str]
    due_date: Optional[date]
    status: str
    confidence: Optional[str]
    review_status: str
    source_quote: Optional[str]
    task_id: str
    assignees: list[dict]             # {name, employee_id} - employee_id None when unmatched


@dataclass
class DecisionRow:
    description: str
    confidence: Optional[str]
    review_status: str
    source_quote: Optional[str]
    decision_id: str


@dataclass
class MeetingMinutesData:
    meeting_id: str
    meeting_date: date
    location: Optional[str]
    audio_url: Optional[str]
    raw_transcript: Optional[str]
    summary: Optional[str]
    review_status: str
    primary_contact_name: Optional[str]
    primary_contact_id: Optional[str]
    connections: list[ConnectionRow]
    tasks: list[TaskRow]
    kind: str
    attendees: list[dict]             # {name, employee_id}
    decisions: list[DecisionRow]


def fetch_task_assignees(conn: psycopg.Connection, task_ids: list[str]) -> dict[str, list[dict]]:
    """task_id -> owners, showing the roster name when matched, else the name as heard."""
    if not task_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            select ta.task_id, coalesce(e.canonical_name, ta.name), ta.employee_id
            from task_assignees ta
            left join entities e on e.id = ta.employee_id
            where ta.task_id = any(%s::uuid[])
            order by 2
            """,
            (task_ids,),
        )
        out: dict[str, list[dict]] = {}
        for tid, name, eid in cur.fetchall():
            out.setdefault(str(tid), []).append({"name": name, "employee_id": (str(eid) if eid else None)})
    return out


def fetch_meeting_minutes_data(conn: psycopg.Connection, meeting_id: str) -> MeetingMinutesData:
    """Everything the meeting view / review screen needs. Excludes rejected
    rows; includes pending ones (flagged in the UI)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.meeting_date, m.location, m.audio_url, m.raw_transcript, m.summary, m.review_status,
                   pc.canonical_name, pc.id, m.kind
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            where m.id = %s
            """,
            (meeting_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No meeting found with id {meeting_id}")
        meeting_date, location, audio_url, raw_transcript, summary, review_status, pc_name, pc_id, kind = row

        cur.execute(
            """
            select coalesce(e.canonical_name, a.name), a.employee_id
            from meeting_attendees a left join entities e on e.id = a.employee_id
            where a.meeting_id = %s order by 1
            """,
            (meeting_id,),
        )
        attendees = [{"name": n, "employee_id": (str(eid) if eid else None)} for n, eid in cur.fetchall()]

        cur.execute(
            """
            select description, confidence, review_status, source_quote, id
            from decisions where meeting_id = %s and review_status <> 'rejected'
            order by created_at, description
            """,
            (meeting_id,),
        )
        decisions = [DecisionRow(d, c, rs, sq, str(i)) for d, c, rs, sq, i in cur.fetchall()]

        cur.execute(
            """
            select e1.canonical_name, e1.id, e2.canonical_name, e2.id,
                   r.description, r.role_tag, r.provenance, r.confidence, r.review_status, r.source_quote, r.id
            from relations r
            join entities e1 on e1.id = r.source_id
            join entities e2 on e2.id = r.target_id
            where r.meeting_id = %s and r.review_status <> 'rejected'
            order by (r.provenance = 'hearsay'), e1.canonical_name
            """,
            (meeting_id,),
        )
        connections = [
            ConnectionRow(s, str(sid), t, str(tid), desc, role, prov, conf, rs, sq, str(rid))
            for s, sid, t, tid, desc, role, prov, conf, rs, sq, rid in cur.fetchall()
        ]

        cur.execute(
            """
            select t.description, e.canonical_name, e.id, t.due_date, t.status,
                   t.confidence, t.review_status, t.source_quote, t.id
            from tasks t
            left join entities e on e.id = t.related_entity_id
            where t.meeting_id = %s and t.review_status <> 'rejected'
            order by t.due_date nulls last
            """,
            (meeting_id,),
        )
        task_rows = cur.fetchall()

    owners = fetch_task_assignees(conn, [str(r[8]) for r in task_rows])
    tasks = [
        TaskRow(desc, name, (str(eid) if eid else None), due, status, conf, rs, sq, str(tid), owners.get(str(tid), []))
        for desc, name, eid, due, status, conf, rs, sq, tid in task_rows
    ]

    return MeetingMinutesData(
        meeting_id=meeting_id,
        meeting_date=meeting_date,
        location=location,
        audio_url=audio_url,
        raw_transcript=raw_transcript,
        summary=summary,
        review_status=review_status,
        primary_contact_name=pc_name,
        primary_contact_id=(str(pc_id) if pc_id else None),
        connections=connections,
        tasks=tasks,
        kind=kind,
        attendees=attendees,
        decisions=decisions,
    )


def generate_readback(conn: psycopg.Connection, meeting_id: str) -> str:
    """The 'here's what I understood' plaintext recap - the LLM summary plus
    the structured connections and tasks, and the raw transcript to check
    against. Also what the CLI prints."""
    d = fetch_meeting_minutes_data(conn, meeting_id)

    lines = [
        "MEETING",
        f"Kind           : {'internal' if d.kind == 'internal' else 'field visit'}",
        f"Date           : {d.meeting_date}",
        f"Primary contact: {d.primary_contact_name or '(none)'}",
        f"Attendees      : {', '.join(a['name'] for a in d.attendees) or '(none recorded)'}",
        f"Review         : {d.review_status}",
        "",
        "SUMMARY",
        d.summary or "(none)",
        "",
        "DECISIONS",
    ]
    if d.decisions:
        for dec in d.decisions:
            flag = "" if dec.review_status == "auto_confirmed" else f"  [{dec.review_status}, {dec.confidence}]"
            lines.append(f"  - {dec.description}{flag}")
    else:
        lines.append("  (none)")

    lines += ["", "CONNECTIONS"]
    if d.connections:
        for c in d.connections:
            flag = "" if c.review_status == "auto_confirmed" else f"  [{c.review_status}, {c.confidence}]"
            tag = f" ({c.role_tag})" if c.role_tag else ""
            lines.append(f"  - {c.description}{tag} [{c.provenance}]{flag}")
    else:
        lines.append("  (none)")

    lines += ["", "TASKS"]
    if d.tasks:
        for t in d.tasks:
            due = f"due {t.due_date}" if t.due_date else "no due date"
            ref = f" -- re: {t.related_entity_name}" if t.related_entity_name else ""
            who = f" -- owner: {', '.join(a['name'] for a in t.assignees)}" if t.assignees else ""
            flag = "" if t.review_status == "auto_confirmed" else f"  [{t.review_status}, {t.confidence}]"
            lines.append(f"  [ ] {t.description} ({due}){ref}{who}{flag}")
    else:
        lines.append("  (none)")

    lines += ["", "-" * 70, "RAW TRANSCRIPT", "", d.raw_transcript or "(none)"]
    return "\n".join(lines)
