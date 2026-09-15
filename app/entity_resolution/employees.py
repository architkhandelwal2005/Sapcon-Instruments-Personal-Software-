"""Match a spoken employee name (from a voice-note task assignment) to an
employee entity. Reuses the same trigram+phonetic candidate retrieval every
other resolution path uses - never an LLM round-trip, just a similarity
threshold, since the employee list is small and this only ever narrows to
one of ~a dozen rows. Below the threshold, leave it unassigned - never guess
which employee was meant."""

from typing import Optional

import psycopg

from app.entity_resolution.matcher import find_candidates

MIN_SCORE = 0.4


def match_employee(conn: psycopg.Connection, name: Optional[str]) -> Optional[str]:
    if not name or not name.strip():
        return None
    candidates = find_candidates(conn, name.strip(), "employee", limit=1)
    if candidates and candidates[0].score >= MIN_SCORE:
        return candidates[0].id
    return None
