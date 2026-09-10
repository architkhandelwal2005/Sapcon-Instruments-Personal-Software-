from dataclasses import dataclass

import jellyfish
import psycopg

PHONETIC_BONUS = 0.15


@dataclass
class Candidate:
    id: str
    canonical_name: str
    aliases: list[str]
    entity_type: str
    title: str | None
    region: str | None
    score: float


def find_candidates(conn: psycopg.Connection, name: str, entity_type: str, limit: int = 6) -> list[Candidate]:
    """Cheap retrieval only - trigram (against canonical_name + aliases) plus a
    phonetic-match bonus for ranking. The actual match/new/uncertain decision
    is made by an LLM in llm_resolve.py with this shortlist + transcript
    context; nothing here decides anything."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, canonical_name, aliases, entity_type, title, region,
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
    for entity_id, canonical_name, aliases, etype, title, region, trigram_score in rows:
        score = float(trigram_score)
        if name_code and jellyfish.metaphone(canonical_name) == name_code:
            score = min(1.0, score + PHONETIC_BONUS)
        candidates.append(
            Candidate(
                id=str(entity_id),
                canonical_name=canonical_name,
                aliases=aliases or [],
                entity_type=etype,
                title=title,
                region=region,
                score=score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
