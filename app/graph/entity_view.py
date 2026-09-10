from dataclasses import dataclass
from typing import Optional

import psycopg


@dataclass
class ConnectionRow:
    direction: str  # "out" | "in" - this entity is the source ("out") or target ("in")
    other_id: str
    other_name: str
    other_type: str
    role_tag: Optional[str]   # soft, editable tag; often null
    description: str           # the plain-language sentence
    provenance: str            # "direct" if any corroborating mention was direct, else "hearsay"
    review_status: str         # worst (least-settled) status across the corroborating rows


_STATUS_RANK = "case r.review_status when 'pending' then 0 when 'auto_confirmed' then 1 when 'confirmed' then 2 else 3 end"


def fetch_entity_connections(conn: psycopg.Connection, entity_id: str) -> list[ConnectionRow]:
    """One entity's connections, deduped to distinct edges (a fact corroborated
    across several meetings is one connection). Keyed by (direction, other
    entity, role_tag) - a differently-tagged edge to the same entity is a
    distinct connection. Rejected rows are excluded; the least-settled status
    among the surviving rows is surfaced so a pending edge is visibly pending."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            with touching as (
                select
                    case when r.source_id = %(entity_id)s then 'out' else 'in' end as direction,
                    case when r.source_id = %(entity_id)s then e2.id else e1.id end as other_id,
                    case when r.source_id = %(entity_id)s then e2.canonical_name else e1.canonical_name end as other_name,
                    case when r.source_id = %(entity_id)s then e2.entity_type else e1.entity_type end as other_type,
                    r.role_tag,
                    r.description,
                    r.provenance,
                    r.review_status,
                    {_STATUS_RANK} as status_rank
                from relations r
                join entities e1 on e1.id = r.source_id
                join entities e2 on e2.id = r.target_id
                where (r.source_id = %(entity_id)s or r.target_id = %(entity_id)s)
                  and r.status = 'active' and r.review_status <> 'rejected'
            )
            select direction, other_id, other_name, other_type, role_tag,
                   (array_agg(description order by status_rank))[1] as description,
                   min(provenance) as provenance,
                   (array_agg(review_status order by status_rank))[1] as review_status
            from touching
            group by direction, other_id, other_name, other_type, role_tag
            order by other_name
            """,
            {"entity_id": entity_id},
        )
        return [
            ConnectionRow(direction, str(other_id), other_name, other_type, role_tag, description, provenance, review_status)
            for direction, other_id, other_name, other_type, role_tag, description, provenance, review_status in cur.fetchall()
        ]
