"""Review gate: the office boy clears every item the pipeline could not
auto-confirm. Auto-confirmed items are already live; pending items are held
out of the trusted views (interaction history, connections, briefs) until a
human confirms them here. Nothing is ever silently dropped - a rejected row
keeps its text and its source_quote in the DB and can be restored.

`kind` is one of: relation | task | decision | entity.
`decision` (the argument) is one of: confirm | reject.
"""

from typing import Optional

import psycopg

_TABLE = {"relation": "relations", "task": "tasks", "decision": "decisions", "entity": "entities"}

# Any unsettled item directly owned by a meeting. Entities are handled separately
# (they belong to a meeting only through its primary contact or its relations).
_PENDING_OWNED = """
    select 1 from relations where meeting_id = %(m)s and review_status = 'pending'
    union all
    select 1 from tasks where meeting_id = %(m)s and review_status = 'pending'
    union all
    select 1 from decisions where meeting_id = %(m)s and review_status = 'pending'
"""


def finalise_meeting_status(conn: psycopg.Connection, meeting_id: str) -> str:
    """Set meetings.review_status to 'pending' while the meeting still has any
    pending relation, task, or attached entity; 'clear' once all are settled.
    Stamps reviewed_at the moment it first goes clear. Returns the new status."""
    pending_items = (
        _PENDING_OWNED
        + """
        union all
        select 1 from entities e where e.review_status = 'pending' and (
            e.id = m.primary_contact_id
            or exists (
                select 1 from relations r
                where r.meeting_id = %(m)s and (r.source_id = e.id or r.target_id = e.id)
                  and r.review_status <> 'rejected'
            )
        )
        """
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            update meetings m set
                review_status = case when exists ({pending_items}) then 'pending' else 'clear' end,
                reviewed_at = case
                    when reviewed_at is null and not exists ({pending_items}) then now()
                    else reviewed_at end
            where m.id = %(m)s
            returning review_status
            """,
            {"m": meeting_id},
        )
        return cur.fetchone()[0]


def pending_summary(conn: psycopg.Connection) -> list[dict]:
    """Meetings with at least one unsettled item, newest first, with counts -
    the /review index."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.id, m.meeting_date, pc.canonical_name, m.kind,
                   (select count(*) from relations r where r.meeting_id = m.id and r.review_status = 'pending') as rel_pending,
                   (select count(*) from tasks t where t.meeting_id = m.id and t.review_status = 'pending') as task_pending,
                   (select count(*) from decisions d where d.meeting_id = m.id and d.review_status = 'pending') as dec_pending,
                   (select count(*) from entities e where e.review_status = 'pending' and (
                        e.id = m.primary_contact_id
                        or exists (select 1 from relations r
                                   where r.meeting_id = m.id and (r.source_id = e.id or r.target_id = e.id)
                                     and r.review_status <> 'rejected'))) as ent_pending
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            where m.review_status = 'pending'
            order by m.meeting_date desc
            """
        )
        rows = cur.fetchall()
    return [
        {
            "meeting_id": str(mid),
            "meeting_date": mdate,
            "primary_contact_name": pc,
            "kind": kind,
            "pending_relations": rp,
            "pending_tasks": tp,
            "pending_decisions": dp,
            "pending_entities": ep,
            "pending_total": rp + tp + dp + ep,
        }
        for mid, mdate, pc, kind, rp, tp, dp, ep in rows
    ]


def pending_count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("select count(*) from meetings where review_status = 'pending'")
        return cur.fetchone()[0]


_CAPTURE_ENTITIES_CTE = """
    with capture_entities as (
        select capture_event_id, id as entity_id from entities where capture_event_id is not null
        union
        select capture_event_id, entity_id from leads where capture_event_id is not null
    )
"""
# Two ways an entity belongs to a capture: it was newly created there
# (entities.capture_event_id), or a lead from there points at it even though the
# entity already existed (leads.capture_event_id) - e.g. a card names someone
# already known from a meeting. Both paths matter for review; UNION dedupes an
# entity that is both (new AND the lead target, the common case).


def pending_captures(conn: psycopg.Connection) -> list[dict]:
    """Capture events (card/diary photos) with at least one linked entity still
    pending - capture_events has no stored review_status of its own (low volume,
    computed is enough), unlike meetings."""
    with conn.cursor() as cur:
        cur.execute(
            _CAPTURE_ENTITIES_CTE
            + """
            select ce.id, ce.capture_type, ce.captured_date, ce.photo_url,
                   count(*) filter (where e.review_status = 'pending') as pending_count,
                   count(*) as total_count
            from capture_events ce
            join capture_entities cx on cx.capture_event_id = ce.id
            join entities e on e.id = cx.entity_id
            group by ce.id, ce.capture_type, ce.captured_date, ce.photo_url
            having count(*) filter (where e.review_status = 'pending') > 0
            order by ce.captured_date desc
            """
        )
        return [
            {
                "capture_event_id": str(cid), "capture_type": ctype, "captured_date": cdate,
                "photo_url": url, "pending_count": pc, "total_count": tc,
            }
            for cid, ctype, cdate, url, pc, tc in cur.fetchall()
        ]


def pending_capture_count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            _CAPTURE_ENTITIES_CTE
            + """
            select count(distinct ce.id) from capture_events ce
            join capture_entities cx on cx.capture_event_id = ce.id
            join entities e on e.id = cx.entity_id and e.review_status = 'pending'
            """
        )
        return cur.fetchone()[0]


def capture_detail(conn: psycopg.Connection, capture_event_id: str) -> dict:
    """The photo plus every entity this capture touched (newly created there, or
    already known and pointed at by one of its leads), each with its review state
    and whatever lead it produced."""
    with conn.cursor() as cur:
        cur.execute(
            "select capture_type, captured_date, photo_url, raw_extraction, logged_by "
            "from capture_events where id = %s",
            (capture_event_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No capture event {capture_event_id!r}")
        capture_type, captured_date, photo_url, raw_extraction, logged_by = row

        cur.execute(
            _CAPTURE_ENTITIES_CTE
            + """
            select e.id, e.canonical_name, e.entity_type, e.title, e.phone, e.email,
                   e.review_status, e.confidence, d.canonical_name,
                   l.id, l.status, l.assigned_to, ae.canonical_name
            from capture_entities cx
            join entities e on e.id = cx.entity_id
            left join entities d on d.id = e.possible_duplicate_of
            left join leads l on l.entity_id = e.id and l.capture_event_id = %(c)s
            left join entities ae on ae.id = l.assigned_to
            where cx.capture_event_id = %(c)s
            order by (e.review_status <> 'pending') desc, e.canonical_name
            """,
            {"c": capture_event_id},
        )
        items = [
            {
                "entity_id": str(eid), "canonical_name": name, "entity_type": etype,
                "title": title, "phone": phone, "email": email,
                "review_status": rs, "confidence": conf, "possible_duplicate_of": dup,
                "lead_id": (str(lid) if lid else None), "lead_status": lstatus,
                "assigned_to": (str(aid) if aid else None), "assigned_name": aname,
            }
            for eid, name, etype, title, phone, email, rs, conf, dup, lid, lstatus, aid, aname in cur.fetchall()
        ]

    return {
        "capture_event_id": capture_event_id, "capture_type": capture_type,
        "captured_date": captured_date, "photo_url": photo_url,
        "raw_extraction": raw_extraction, "logged_by": logged_by, "entries": items,
    }


def meeting_entities(conn: psycopg.Connection, meeting_id: str) -> list[dict]:
    """Entities attached to a meeting (primary contact or an endpoint of one of
    its non-rejected relations), with their review state and any possible
    duplicate - so the reviewer can settle them alongside the connections."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select e.id, e.canonical_name, e.entity_type, e.review_status,
                   e.confidence, d.canonical_name
            from entities e
            left join entities d on d.id = e.possible_duplicate_of
            where e.id = (select primary_contact_id from meetings where id = %(m)s)
               or e.id in (
                    select source_id from relations where meeting_id = %(m)s and review_status <> 'rejected'
                    union
                    select target_id from relations where meeting_id = %(m)s and review_status <> 'rejected'
               )
            order by (e.review_status <> 'pending'), e.canonical_name
            """,
            {"m": meeting_id},
        )
        return [
            {
                "entity_id": str(eid),
                "canonical_name": name,
                "entity_type": etype,
                "review_status": rs,
                "confidence": conf,
                "possible_duplicate_of": dup,
            }
            for eid, name, etype, rs, conf, dup in cur.fetchall()
        ]


def rejected_items(conn: psycopg.Connection, meeting_id: str) -> dict:
    """Rejected relations/tasks for this meeting - shown at the bottom of the
    review screen with a restore action so a mis-reject is never final."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select r.id, e1.canonical_name, e2.canonical_name, r.description
            from relations r
            join entities e1 on e1.id = r.source_id
            join entities e2 on e2.id = r.target_id
            where r.meeting_id = %s and r.review_status = 'rejected'
            order by e1.canonical_name
            """,
            (meeting_id,),
        )
        relations = [
            {"id": str(i), "source": s, "target": t, "description": d}
            for i, s, t, d in cur.fetchall()
        ]
        cur.execute(
            "select id, description from tasks where meeting_id = %s and review_status = 'rejected' order by description",
            (meeting_id,),
        )
        tasks = [{"id": str(i), "description": d} for i, d in cur.fetchall()]
        cur.execute(
            "select id, description from decisions where meeting_id = %s and review_status = 'rejected' order by description",
            (meeting_id,),
        )
        decisions = [{"id": str(i), "description": d} for i, d in cur.fetchall()]
    return {"relations": relations, "tasks": tasks, "decisions": decisions}


def _affected_meetings(conn: psycopg.Connection, kind: str, item_id: str) -> list[str]:
    with conn.cursor() as cur:
        if kind == "entity":
            cur.execute(
                """
                select id from meetings where primary_contact_id = %(e)s
                union
                select meeting_id from relations where source_id = %(e)s or target_id = %(e)s
                """,
                {"e": item_id},
            )
        else:
            cur.execute(f"select meeting_id from {_TABLE[kind]} where id = %s", (item_id,))
        return [str(r[0]) for r in cur.fetchall() if r[0] is not None]


def apply_decision(
    conn: psycopg.Connection,
    kind: str,
    item_id: str,
    decision: str,
    *,
    description: Optional[str] = None,
    role_tag: Optional[str] = None,
    due_date=None,
    actor_id: Optional[str] = None,
    note: Optional[str] = None,
) -> list[str]:
    """Confirm or reject one item, applying any edits passed alongside a
    confirm, then re-finalise every meeting the item touches. Returns the
    affected meeting ids. Restoring a rejected item = confirm it again.

    Every decision is also written to review_decisions. That table is
    append-only, so a reject and a later restore both survive - which a pair of
    columns on each table could not express. `actor_id` is None for scripts and
    for anything decided before logins existed."""
    if kind not in _TABLE:
        raise ValueError(f"unknown kind {kind!r}")
    if decision not in ("confirm", "reject"):
        raise ValueError(f"unknown decision {decision!r}")

    new_status = "confirmed" if decision == "confirm" else "rejected"
    meetings = _affected_meetings(conn, kind, item_id)

    with conn.cursor() as cur:
        if kind == "relation":
            if decision == "confirm" and description is not None:
                cur.execute(
                    "update relations set review_status = 'confirmed', description = %s, role_tag = %s where id = %s",
                    (description.strip(), (role_tag or None), item_id),
                )
            else:
                cur.execute("update relations set review_status = %s where id = %s", (new_status, item_id))

        elif kind == "task":
            if decision == "confirm" and description is not None:
                cur.execute(
                    "update tasks set review_status = 'confirmed', description = %s, due_date = %s where id = %s",
                    (description.strip(), due_date, item_id),
                )
            else:
                cur.execute("update tasks set review_status = %s where id = %s", (new_status, item_id))

        elif kind == "decision":
            if decision == "confirm" and description is not None:
                cur.execute(
                    "update decisions set review_status = 'confirmed', description = %s where id = %s",
                    (description.strip(), item_id),
                )
            else:
                cur.execute("update decisions set review_status = %s where id = %s", (new_status, item_id))

        elif kind == "entity":
            if decision == "confirm":
                cur.execute(
                    "update entities set review_status = 'confirmed', possible_duplicate_of = null where id = %s",
                    (item_id,),
                )
            else:
                # A relation to a non-entity is meaningless - reject those too.
                # Tasks keep their text; their related_entity_id still resolves
                # (the row survives) and every task query filters on the task's
                # own review_status, not the entity's.
                cur.execute("update entities set review_status = 'rejected' where id = %s", (item_id,))
                cur.execute(
                    "update relations set review_status = 'rejected' "
                    "where (source_id = %s or target_id = %s) and review_status <> 'confirmed'",
                    (item_id, item_id),
                )
            cur.execute(
                "update entity_review_queue set resolved = true where entity_id = %s or possible_duplicate_of = %s",
                (item_id, item_id),
            )

        cur.execute(
            "insert into review_decisions (kind, item_id, decision, decided_by, note) "
            "values (%s, %s, %s, %s, %s)",
            (kind, item_id, decision, actor_id, note),
        )

    for m in meetings:
        finalise_meeting_status(conn, m)
    conn.commit()
    return meetings
