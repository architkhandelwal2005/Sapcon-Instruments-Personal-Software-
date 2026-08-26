from dataclasses import dataclass
from typing import Optional

import psycopg

DEFAULT_MAX_DEPTH = 6


@dataclass
class PathStep:
    from_id: str
    to_id: str
    relation_type: str
    provenance: str
    reversed: bool  # True if traversed against the stored source->target direction


@dataclass
class Path:
    node_ids: list[str]
    steps: list[PathStep]


def find_path(
    conn: psycopg.Connection, start_id: str, end_id: str, max_depth: int = DEFAULT_MAX_DEPTH
) -> Optional[Path]:
    """Shortest path between two entities, treating relations as traversable
    in either direction - "how does X connect to Y" is about network
    connectivity, not the direction any single relation happens to point.
    Each step still records the real relation_type/direction/provenance so
    callers can render a readable explanation of the path."""
    if start_id == end_id:
        return Path(node_ids=[start_id], steps=[])

    with conn.cursor() as cur:
        cur.execute(
            """
            with recursive edges as (
                select source_id, target_id, relation_type, provenance, false as reversed
                from relations where status = 'active'
                union all
                select target_id as source_id, source_id as target_id, relation_type, provenance, true as reversed
                from relations where status = 'active'
            ),
            paths as (
                select
                    %(start_id)s::uuid as current_id,
                    array[%(start_id)s::uuid] as node_path,
                    array[]::text[] as relation_path,
                    array[]::boolean[] as reversed_path,
                    array[]::text[] as provenance_path,
                    0 as depth

                union all

                select
                    e.target_id,
                    p.node_path || e.target_id,
                    p.relation_path || e.relation_type,
                    p.reversed_path || e.reversed,
                    p.provenance_path || e.provenance,
                    p.depth + 1
                from paths p
                join edges e on e.source_id = p.current_id
                where not (e.target_id = any(p.node_path))
                  and p.depth < %(max_depth)s
            )
            select node_path, relation_path, reversed_path, provenance_path
            from paths
            where current_id = %(end_id)s and depth > 0
            order by depth
            limit 1
            """,
            {"start_id": start_id, "end_id": end_id, "max_depth": max_depth},
        )
        row = cur.fetchone()

    if row is None:
        return None

    node_path, relation_path, reversed_path, provenance_path = row
    node_ids = [str(n) for n in node_path]
    steps = [
        PathStep(
            from_id=node_ids[i],
            to_id=node_ids[i + 1],
            relation_type=relation_path[i],
            provenance=provenance_path[i],
            reversed=reversed_path[i],
        )
        for i in range(len(relation_path))
    ]
    return Path(node_ids=node_ids, steps=steps)
