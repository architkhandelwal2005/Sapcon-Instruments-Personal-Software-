"""Query-time answers, read straight off the verified meeting notes.

- brief(entity)      : who they are, our history, open commitments, connections
- connect(a, b)      : how two entities are connected, from meetings touching both
- ask(question)      : free-text Q&A; resolves entity mentions, retrieves their
                       meetings (or recent ones as a fallback), synthesises

Every answer carries citations that each resolve to a verbatim transcript span
(see app.query.synthesize).
"""

from dataclasses import dataclass
from typing import Literal

import psycopg

from app.query.retrieve import (
    meetings_for_any,
    meetings_for_entity,
    meetings_for_pair,
    recent_meetings,
    resolve_mentions,
)
from app.query.synthesize import QueryAnswer, answer_from_notes

AskMode = Literal["brief", "connect", "general"]


@dataclass
class AskResult:
    question: str
    mode: AskMode
    entities: list[tuple[str, str]]  # (id, name) resolved from the question
    answer: QueryAnswer


def _entity_name(conn: psycopg.Connection, entity_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("select canonical_name from entities where id = %s", (entity_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No entity {entity_id!r}")
        return row[0]


def brief(conn: psycopg.Connection, entity_id: str) -> tuple[str, QueryAnswer]:
    name = _entity_name(conn, entity_id)
    notes = meetings_for_entity(conn, entity_id)
    question = (
        f"Brief me on {name} before I meet them again: who they are, the history of our "
        f"dealings, any open commitments on either side, and how they connect to other people "
        f"or companies."
    )
    return name, answer_from_notes(question, notes)


def connect(conn: psycopg.Connection, a_id: str, b_id: str) -> tuple[str, str, QueryAnswer]:
    a_name, b_name = _entity_name(conn, a_id), _entity_name(conn, b_id)
    notes = meetings_for_pair(conn, a_id, b_id)
    question = (
        f"How are {a_name} and {b_name} connected? Explain the relationship between them and "
        f"anything that ties them together across these meetings."
    )
    return a_name, b_name, answer_from_notes(question, notes)


def ask(conn: psycopg.Connection, question: str) -> AskResult:
    mentions = resolve_mentions(conn, question)
    ids = [eid for eid, _ in mentions]

    if len(ids) >= 2:
        notes = meetings_for_pair(conn, ids[0], ids[1])
        if not notes:  # no shared meeting - widen to anything touching either
            notes = meetings_for_any(conn, ids)
        mode: AskMode = "connect"
    elif len(ids) == 1:
        notes = meetings_for_entity(conn, ids[0])
        mode = "brief"
    else:
        notes = recent_meetings(conn)
        mode = "general"

    return AskResult(question=question, mode=mode, entities=mentions, answer=answer_from_notes(question, notes))
