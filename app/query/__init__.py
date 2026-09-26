"""Query-time answers, read off the meeting notes and the CRM's own records.

- brief(entity)      : who they are, our history, open commitments, connections
- connect(a, b)      : how two entities are connected, from meetings touching both
- ask(question)      : free-text Q&A; resolves entity mentions, retrieves their
                       meetings (or recent ones as a fallback), synthesises

A claim from a meeting carries a verbatim transcript quote; a claim from a
record carries the record's reference. Both are checked (see
app.query.synthesize), so an answer can be traced back to something real.
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
from app.query.budget import FACT_SHARE, MAX_CONTEXT_CHARS, pack_notes
from app.query.facts import FactPack, build_fact_pack
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


def _answer(conn: psycopg.Connection, question: str, notes, entity_ids: list[str]) -> QueryAnswer:
    """One place where the budget is split and the records are gathered, so a
    brief, a connection and a free-text question all behave the same."""
    fact_budget = int(MAX_CONTEXT_CHARS * FACT_SHARE)
    facts = build_fact_pack(conn, entity_ids, question, max_chars=fact_budget)
    spent = sum(len(f.text) for f in facts.facts)
    packed, dropped = pack_notes(notes, budget=MAX_CONTEXT_CHARS - spent)
    return answer_from_notes(question, packed, facts=facts, notes_dropped=dropped)


def brief(conn: psycopg.Connection, entity_id: str) -> tuple[str, QueryAnswer]:
    name = _entity_name(conn, entity_id)
    notes = meetings_for_entity(conn, entity_id)
    question = (
        f"Brief me on {name} before I meet them again: who they are, the history of our "
        f"dealings, any open commitments on either side, and how they connect to other people "
        f"or companies."
    )
    return name, _answer(conn, question, notes, [entity_id])


def connect(conn: psycopg.Connection, a_id: str, b_id: str) -> tuple[str, str, QueryAnswer]:
    a_name, b_name = _entity_name(conn, a_id), _entity_name(conn, b_id)
    notes = meetings_for_pair(conn, a_id, b_id)
    question = (
        f"How are {a_name} and {b_name} connected? Explain the relationship between them and "
        f"anything that ties them together across these meetings."
    )
    return a_name, b_name, _answer(conn, question, notes, [a_id, b_id])


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

    return AskResult(question=question, mode=mode, entities=mentions,
                     answer=_answer(conn, question, notes, ids))
