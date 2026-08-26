from dataclasses import dataclass

import psycopg


@dataclass
class ConnectionRow:
    direction: str  # "out" | "in" - this entity is the source ("out") or target ("in")
    other_id: str
    other_name: str
    other_type: str
    relation_type: str
    provenance: str  # "direct" if any corroborating mention was direct, else "hearsay"


def fetch_entity_connections(conn: psycopg.Connection, entity_id: str) -> list[ConnectionRow]:
    """All of one entity's direct connections, deduped to distinct edges
    (same rule as app.graph.centrality: a fact corroborated across multiple
    meetings is one connection, not one per meeting) - shared by the
    Contact/Company profile's condensed view and the full Contour view, so
    both show exactly the same underlying picture."""
    with conn.cursor() as cur:
        cur.execute(
            """
            with touching as (
                select
                    case when r.source_id = %(entity_id)s then 'out' else 'in' end as direction,
                    case when r.source_id = %(entity_id)s then e2.id else e1.id end as other_id,
                    case when r.source_id = %(entity_id)s then e2.canonical_name else e1.canonical_name end as other_name,
                    case when r.source_id = %(entity_id)s then e2.entity_type else e1.entity_type end as other_type,
                    r.relation_type,
                    r.provenance
                from relations r
                join entities e1 on e1.id = r.source_id
                join entities e2 on e2.id = r.target_id
                where (r.source_id = %(entity_id)s or r.target_id = %(entity_id)s) and r.status = 'active'
            )
            select direction, other_id, other_name, other_type, relation_type, min(provenance) as provenance
            from touching
            group by direction, other_id, other_name, other_type, relation_type
            order by other_name
            """,
            {"entity_id": entity_id},
        )
        return [
            ConnectionRow(direction, str(other_id), other_name, other_type, relation_type, provenance)
            for direction, other_id, other_name, other_type, relation_type, provenance in cur.fetchall()
        ]
