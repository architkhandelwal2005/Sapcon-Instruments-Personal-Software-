"""Pull the raw material a query-time answer is built from: the transcripts
and summaries of the meetings that actually touch the entities in question.
The synthesis step reads these; every claim it makes is grounded back against
one of these transcripts.

Rejected relations/tasks are not a retrieval path (that connection was judged
wrong), but a meeting still comes in if the entity reaches it another way.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import psycopg


@dataclass
class MeetingNote:
    meeting_id: str
    meeting_date: date
    primary_contact_name: Optional[str]
    summary: Optional[str]
    transcript: str


def _rows_to_notes(rows) -> list[MeetingNote]:
    return [
        MeetingNote(str(mid), mdate, pc, summary, transcript or "")
        for mid, mdate, pc, summary, transcript in rows
    ]


_SELECT = """
    select m.id, m.meeting_date, pc.canonical_name, m.summary, m.raw_transcript
    from meetings m
    left join entities pc on pc.id = m.primary_contact_id
"""

_TOUCHES = """
    m.primary_contact_id = %(e)s
    or m.id in (
        select meeting_id from relations
        where (source_id = %(e)s or target_id = %(e)s) and review_status <> 'rejected'
        union
        select meeting_id from tasks where related_entity_id = %(e)s and review_status <> 'rejected'
    )
"""


def meetings_for_entity(conn: psycopg.Connection, entity_id: str) -> list[MeetingNote]:
    with conn.cursor() as cur:
        cur.execute(_SELECT + f"where {_TOUCHES} order by m.meeting_date desc", {"e": entity_id})
        return _rows_to_notes(cur.fetchall())


def meetings_for_pair(conn: psycopg.Connection, a_id: str, b_id: str) -> list[MeetingNote]:
    """Meetings that touch BOTH entities - the direct evidence for how two
    entities are connected."""
    with conn.cursor() as cur:
        cur.execute(
            _SELECT
            + f"where ({_TOUCHES.replace('%(e)s', '%(a)s')}) and ({_TOUCHES.replace('%(e)s', '%(b)s')}) "
            + "order by m.meeting_date desc",
            {"a": a_id, "b": b_id},
        )
        return _rows_to_notes(cur.fetchall())


def meetings_for_any(conn: psycopg.Connection, entity_ids: list[str]) -> list[MeetingNote]:
    """Meetings touching any of the given entities, deduped - used when a
    free-text question mentions several entities."""
    if not entity_ids:
        return []
    seen: dict[str, MeetingNote] = {}
    for eid in entity_ids:
        for note in meetings_for_entity(conn, eid):
            seen[note.meeting_id] = note
    return sorted(seen.values(), key=lambda n: n.meeting_date, reverse=True)


def recent_meetings(conn: psycopg.Connection, limit: int = 10) -> list[MeetingNote]:
    with conn.cursor() as cur:
        cur.execute(_SELECT + "order by m.meeting_date desc limit %(limit)s", {"limit": limit})
        return _rows_to_notes(cur.fetchall())


def resolve_mentions(conn: psycopg.Connection, question: str) -> list[tuple[str, str]]:
    """(entity_id, canonical_name) for every entity whose name or alias appears
    verbatim in the question. Deterministic - no LLM. Longer names win when one
    contains another so "Reliance Cement Ltd" doesn't also pull a bare
    "Reliance"."""
    with conn.cursor() as cur:
        # \y = word boundary, so "Reliance" doesn't match inside another word
        # and a 2-letter name can't match mid-token. Names are escaped for regex.
        cur.execute(
            r"""
            select id, canonical_name
            from entities
            where review_status <> 'rejected' and (
                %(q)s ~* ('\y' || regexp_replace(canonical_name, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g') || '\y')
                or exists (
                    select 1 from unnest(aliases) a
                    where %(q)s ~* ('\y' || regexp_replace(a, '([.^$*+?()\[\]{}|\\-])', '\\\1', 'g') || '\y')
                )
            )
            order by length(canonical_name) desc
            """,
            {"q": question},
        )
        hits = cur.fetchall()

    chosen: list[tuple[str, str]] = []
    claimed_names: list[str] = []
    for eid, name in hits:
        if any(name.lower() in longer.lower() and name.lower() != longer.lower() for longer in claimed_names):
            continue
        chosen.append((str(eid), name))
        claimed_names.append(name)

    if not chosen:
        chosen = _resolve_first_names(conn, question)
    return chosen


# People are called by one name in speech - "tell Vishal to call him", "what is
# pending with Saurabh" - while the roster holds "Vishal Dixit". Matching only
# whole names meant those questions resolved to nobody.
_MIN_FIRST_NAME = 4


def _resolve_first_names(conn: psycopg.Connection, question: str) -> list[tuple[str, str]]:
    """Entities identified by a single name part.

    Staff first: "tell Vishal to call him" means the Vishal on the roster, even
    though six customers called Vishal have come in from visiting cards - the
    team is a closed set of thirty people he names constantly, and a customer is
    normally named in full ("Vishal Rabari"), which the whole-name pass catches
    before this one runs.

    Outside the roster the name must be unique: two customers called Vishal
    means neither is chosen, and the question is answered from the wider
    material rather than from a guess about which one was meant."""
    for entity_types in (("employee",), ("person",)):
        with conn.cursor() as cur:
            cur.execute(
                r"""
                with parts as (
                    select id, canonical_name, lower(part) as part
                    from entities, unnest(string_to_array(canonical_name, ' ')) as part
                    where review_status <> 'rejected'
                      and entity_type = any(%(types)s)
                      and length(part) >= %(min_len)s
                ),
                unique_parts as (
                    select part from parts group by part having count(distinct id) = 1
                )
                select distinct p.id, p.canonical_name
                from parts p join unique_parts u on u.part = p.part
                where %(q)s ~* ('\y' || regexp_replace(p.part, '([.^$*+?()\[\]{}|\-])', '\', 'g') || '\y')
                """,
                {"q": question, "min_len": _MIN_FIRST_NAME, "types": list(entity_types)},
            )
            found = [(str(eid), name) for eid, name in cur.fetchall()]
        if found:
            return found
    return []
