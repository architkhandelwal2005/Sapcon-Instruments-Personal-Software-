from typing import Optional

import psycopg

# Both queries dedupe to distinct (source, relation_type, target) edges before
# counting. The same fact can be inserted as multiple relation rows - one per
# corroborating meeting (needed for step 7's independent-corroboration
# check) - so a raw row count would inflate degree for anything mentioned
# repeatedly rather than measuring how many distinct entities it connects to.

_DISTINCT_EDGES_CTE = """
    with distinct_edges as (
        select distinct source_id, target_id, relation_type
        from relations
        where status = 'active'
    )
"""


def total_degree(conn: psycopg.Connection, limit: int = 20) -> list[tuple]:
    """Coarse, relation-agnostic in+out degree - a rough 'how connected is
    this entity' signal only. See relation_type_counts() for the metric
    that actually answers real questions."""
    with conn.cursor() as cur:
        cur.execute(
            _DISTINCT_EDGES_CTE
            + """
            , endpoints as (
                select source_id as entity_id from distinct_edges
                union all
                select target_id as entity_id from distinct_edges
            )
            select e.canonical_name, e.entity_type, counts.degree
            from (
                select entity_id, count(*) as degree
                from endpoints
                group by entity_id
            ) as counts
            join entities e on e.id = counts.entity_id
            order by counts.degree desc
            limit %(limit)s
            """,
            {"limit": limit},
        )
        return cur.fetchall()


def relation_type_counts(
    conn: psycopg.Connection,
    relation_type: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = 20,
) -> list[tuple]:
    """Per-entity counts broken out by relation_type and direction - e.g.
    relation_type='end_user_of', direction='in' answers "which entities have
    the most known end users". This is the metric real questions need, not
    total_degree."""
    where = ["1=1"]
    params: dict = {"limit": limit}
    if relation_type is not None:
        where.append("counts.relation_type = %(relation_type)s")
        params["relation_type"] = relation_type
    if direction is not None:
        where.append("counts.direction = %(direction)s")
        params["direction"] = direction

    query = (
        _DISTINCT_EDGES_CTE
        + f"""
        , endpoints as (
            select source_id as entity_id, relation_type, 'out' as direction from distinct_edges
            union all
            select target_id as entity_id, relation_type, 'in' as direction from distinct_edges
        )
        select e.canonical_name, e.entity_type, counts.relation_type, counts.direction, counts.cnt
        from (
            select entity_id, relation_type, direction, count(*) as cnt
            from endpoints
            group by entity_id, relation_type, direction
        ) as counts
        join entities e on e.id = counts.entity_id
        where {' and '.join(where)}
        order by counts.cnt desc
        limit %(limit)s
        """
    )
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()
