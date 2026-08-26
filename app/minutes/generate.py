from dataclasses import dataclass
from datetime import date
from typing import Optional

import psycopg


@dataclass
class RelationRow:
    source: str
    relation_type: str
    target: str
    provenance: str


@dataclass
class TaskRow:
    description: str
    related_entity_name: Optional[str]
    due_date: Optional[date]
    status: str


@dataclass
class MeetingMinutesData:
    meeting_id: str
    meeting_date: date
    location: Optional[str]
    audio_url: Optional[str]
    raw_transcript: Optional[str]
    primary_contact_name: Optional[str]
    relations: list[RelationRow]
    tasks: list[TaskRow]

    @property
    def direct_relations(self) -> list[RelationRow]:
        return [r for r in self.relations if r.provenance == "direct"]

    @property
    def hearsay_relations(self) -> list[RelationRow]:
        return [r for r in self.relations if r.provenance == "hearsay"]


def fetch_meeting_minutes_data(conn: psycopg.Connection, meeting_id: str) -> MeetingMinutesData:
    """The single source of truth for what a meeting's minutes contain -
    used both to render the stored plaintext minutes (generate_minutes
    below) and the web app's HTML meeting view, so both are guaranteed to
    show exactly the same underlying data, just formatted differently."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.meeting_date, m.location, m.audio_url, m.raw_transcript, pc.canonical_name
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            where m.id = %s
            """,
            (meeting_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No meeting found with id {meeting_id}")
        meeting_date, location, audio_url, raw_transcript, primary_contact_name = row

        cur.execute(
            """
            select e1.canonical_name, r.relation_type, e2.canonical_name, r.provenance
            from relations r
            join entities e1 on e1.id = r.source_id
            join entities e2 on e2.id = r.target_id
            where r.meeting_id = %s and r.status = 'active'
            order by (r.provenance = 'hearsay'), e1.canonical_name
            """,
            (meeting_id,),
        )
        relations = [RelationRow(source, relation_type, target, provenance) for source, relation_type, target, provenance in cur.fetchall()]

        cur.execute(
            """
            select t.description, e.canonical_name, t.due_date, t.status
            from tasks t
            left join entities e on e.id = t.related_entity_id
            where t.meeting_id = %s
            order by t.due_date nulls last
            """,
            (meeting_id,),
        )
        tasks = [TaskRow(description, related_name, due_date, status) for description, related_name, due_date, status in cur.fetchall()]

    return MeetingMinutesData(
        meeting_id=meeting_id,
        meeting_date=meeting_date,
        location=location,
        audio_url=audio_url,
        raw_transcript=raw_transcript,
        primary_contact_name=primary_contact_name,
        relations=relations,
        tasks=tasks,
    )


def generate_minutes(conn: psycopg.Connection, meeting_id: str) -> str:
    """Render a meeting's stored relations/tasks into readable plaintext
    minutes (stored on meetings.minutes; also what the CLI prints).

    This is a pure formatter over rows already in the DB - no LLM call, no
    independent summarization of the transcript. The minutes can never say
    anything the graph doesn't already contain: if something's missing here,
    it's missing from the graph, not just from this summary, so a correction
    made from reading the minutes fixes the real data.
    """
    data = fetch_meeting_minutes_data(conn, meeting_id)

    lines = [
        "MEETING MINUTES",
        f"Meeting ID     : {data.meeting_id}",
        f"Date           : {data.meeting_date}",
        f"Primary contact: {data.primary_contact_name or '(none)'}",
        f"Location       : {data.location or '(not recorded)'}",
    ]
    if data.audio_url:
        lines.append(f"Audio file     : {data.audio_url}")

    lines += ["", "RELATIONSHIPS"]
    if data.direct_relations:
        lines.append("  Direct:")
        lines += [f"    - {r.source} {r.relation_type} {r.target}" for r in data.direct_relations]
    if data.hearsay_relations:
        lines.append("  Hearsay (unverified):")
        lines += [f"    - {r.source} {r.relation_type} {r.target}" for r in data.hearsay_relations]
    if not data.relations:
        lines.append("  (none extracted)")

    lines += ["", "TASKS"]
    if data.tasks:
        for t in data.tasks:
            due_str = f"due {t.due_date}" if t.due_date else "no due date"
            ref = f" -- re: {t.related_entity_name}" if t.related_entity_name else ""
            marker = "x" if t.status == "done" else " "
            lines.append(f"  [{marker}] {t.description} ({due_str}){ref}")
    else:
        lines.append("  (none extracted)")

    lines += [
        "",
        "-" * 70,
        "RAW TRANSCRIPT (check the above against this -- if something's missing above,",
        "it's missing from the graph, not just this summary; correct it with a follow-up",
        "voice note appended to this meeting)",
        "",
        data.raw_transcript or "(no transcript stored)",
    ]

    return "\n".join(lines)


def store_minutes(conn: psycopg.Connection, meeting_id: str) -> str:
    minutes = generate_minutes(conn, meeting_id)
    with conn.cursor() as cur:
        cur.execute(
            "update meetings set minutes = %s, minutes_generated_at = now() where id = %s",
            (minutes, meeting_id),
        )
    return minutes
