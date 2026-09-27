"""Staff names: the roster handed to extraction, and matching an extracted
name (attendee, task owner) back to an employee entity. Exact name/alias
first, then a strict typo-level fuzzy fallback over the same trigram
candidate retrieval every other resolution path uses. Anything short of
that stays unmatched and is shown as heard - never guess which employee
was meant."""

import re
from typing import Optional

import psycopg

from app.entity_resolution.matcher import find_candidates

MIN_SCORE = 0.75


def employee_roster(conn: psycopg.Connection) -> list[str]:
    """Staff names for the extraction prompt, each with its other spellings
    (initials, short forms) so a spoken "VT" or "Sanjivni" maps to one name."""
    with conn.cursor() as cur:
        cur.execute(
            "select canonical_name, aliases from entities "
            "where entity_type = 'employee' and review_status <> 'rejected' order by canonical_name"
        )
        rows = cur.fetchall()
    out = []
    for name, aliases in rows:
        others = [a for a in (aliases or []) if a and a != name]
        out.append(f"{name} (also written: {', '.join(others)})" if others else name)
    return out


def match_employee(conn: psycopg.Connection, name: Optional[str]) -> Optional[str]:
    name = re.sub(r"\s*\(also written:.*\)\s*$", "", name or "").strip()
    if not name:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "select id from entities where entity_type = 'employee' and review_status <> 'rejected' "
            "and (lower(canonical_name) = lower(%(n)s) "
            "     or exists (select 1 from unnest(aliases) a where lower(a) = lower(%(n)s)))",
            {"n": name},
        )
        exact = cur.fetchall()
    if len(exact) == 1:
        return str(exact[0][0])
    if len(exact) > 1:
        return None  # same spelling on two people - never guess
    # Fuzzy only absorbs typo-level variants ("Vedant B" / "Anshul Namde"). A
    # partial name ("Sumit") is left unmatched: extraction is told to use the
    # roster spelling when sure, so a bare first name means it wasn't - and
    # the same first name can belong to someone not on the roster at all.
    candidates = find_candidates(conn, name, "employee", limit=1)
    if (
        candidates
        and candidates[0].score >= MIN_SCORE
        and len(name.split()) == len(candidates[0].canonical_name.split())
    ):
        return candidates[0].id
    return None


def find_employee_by_spoken_name(
    conn: psycopg.Connection, name: Optional[str]
) -> Optional[tuple[str, str]]:
    """(entity_id, canonical_name) for a name said out loud, or None.

    `match_employee` deliberately refuses a bare first name: it decides who an
    extracted task belongs to, and a stray "Sumit" in a recap may be anyone. An
    instruction is different - "assign it to Vishal" is addressed to the roster,
    and getting no match means the instruction silently does nothing.

    So a first name is accepted here, but only when exactly one person on the
    roster answers to it. Two Vishals on the team means neither is chosen.
    """
    cleaned = re.sub(r"\s*\(also written:.*\)\s*$", "", name or "").strip()
    if not cleaned:
        return None

    exact = match_employee(conn, cleaned)
    if exact:
        with conn.cursor() as cur:
            cur.execute("select canonical_name from entities where id = %s", (exact,))
            row = cur.fetchone()
        return (exact, row[0]) if row else None

    if len(cleaned.split()) != 1 or len(cleaned) < 3:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, canonical_name from entities
            where entity_type = 'employee' and review_status <> 'rejected'
              and lower(%(n)s) = any (
                  select lower(part) from unnest(string_to_array(canonical_name, ' ')) as part
              )
            """,
            {"n": cleaned},
        )
        found = cur.fetchall()
    if len(found) == 1:
        return str(found[0][0]), found[0][1]
    return None
