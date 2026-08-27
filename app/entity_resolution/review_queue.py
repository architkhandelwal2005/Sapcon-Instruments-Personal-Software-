from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass
class ReviewFlag:
    id: str
    other_entity_id: str
    other_entity_name: str
    created_at: datetime


def fetch_flags_for_entity(conn: psycopg.Connection, entity_id: str) -> dict:
    """Unresolved entity_review_queue flags touching this entity, from both
    directions - view-only, no resolve/merge action yet:
    - as_new: this entity was auto-created on an ambiguous match; it might
      be a duplicate of `other_entity`.
    - as_target: some other entity was auto-created and almost matched THIS
      one instead; this entity might have an undiscovered duplicate.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select q.id, d.id, d.canonical_name, q.created_at
            from entity_review_queue q
            join entities d on d.id = q.possible_duplicate_of
            where q.entity_id = %(entity_id)s and not q.resolved
            order by q.created_at desc
            """,
            {"entity_id": entity_id},
        )
        as_new = [ReviewFlag(str(i), str(oid), oname, created_at) for i, oid, oname, created_at in cur.fetchall()]

        cur.execute(
            """
            select q.id, e.id, e.canonical_name, q.created_at
            from entity_review_queue q
            join entities e on e.id = q.entity_id
            where q.possible_duplicate_of = %(entity_id)s and not q.resolved
            order by q.created_at desc
            """,
            {"entity_id": entity_id},
        )
        as_target = [ReviewFlag(str(i), str(oid), oname, created_at) for i, oid, oname, created_at in cur.fetchall()]

    return {"as_new": as_new, "as_target": as_target}
