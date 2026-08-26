from dataclasses import dataclass

import jellyfish
import psycopg

# Thresholds per PLAN.md ambiguity #3 — starting points, tuned against real
# data once available.
AUTO_LINK_THRESHOLD = 0.7
CONFIRM_THRESHOLD = 0.4
PHONETIC_BONUS = 0.15


@dataclass
class Candidate:
    id: str
    canonical_name: str
    aliases: list[str]
    score: float


def find_candidates(conn: psycopg.Connection, name: str, entity_type: str, limit: int = 5) -> list[Candidate]:
    """Trigram similarity (against canonical_name and every alias) as the
    primary signal, with a phonetic (metaphone) match as a secondary bonus —
    see PLAN.md "Flags on the cost policy" #2 for why phonetic over embeddings."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, canonical_name, aliases,
                   greatest(
                       similarity(canonical_name, %(name)s),
                       coalesce((select max(similarity(alias, %(name)s)) from unnest(aliases) as alias), 0)
                   ) as score
            from entities
            where entity_type = %(entity_type)s
            order by score desc
            limit %(limit)s
            """,
            {"name": name, "entity_type": entity_type, "limit": limit},
        )
        rows = cur.fetchall()

    name_code = jellyfish.metaphone(name)
    candidates = []
    for entity_id, canonical_name, aliases, trigram_score in rows:
        score = float(trigram_score)
        if name_code and jellyfish.metaphone(canonical_name) == name_code:
            score = min(1.0, score + PHONETIC_BONUS)
        candidates.append(
            Candidate(id=str(entity_id), canonical_name=canonical_name, aliases=aliases or [], score=score)
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
