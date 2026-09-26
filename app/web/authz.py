"""What a particular employee is allowed to see.

The middleware decides which pages a role may open. It cannot decide whether
*this* employee may open *that* lead, because it runs before routing and has no
path parameters - so per-row checks live here and are called from handlers.

The rule for an employee is: their own work, and the customers they reach
through it. Not the whole book. Around 700 contacts with phone numbers and email
addresses is the thing that walks out of the door when someone leaves, so an
employee reaches a customer only through a lead, a task or a meeting of their
own.

A page they may not see returns 404 rather than 403: telling someone "this lead
exists but is not yours" is itself information about who the company is talking
to.
"""

import psycopg

from app.web.auth import Actor


def employee_owns_task(conn: psycopg.Connection, actor: Actor, task_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from task_assignees where task_id = %s and employee_id = %s",
            (task_id, actor.entity_id),
        )
        return cur.fetchone() is not None


def employee_owns_lead(conn: psycopg.Connection, actor: Actor, lead_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from leads where id = %s and assigned_to = %s",
            (lead_id, actor.entity_id),
        )
        return cur.fetchone() is not None


def employee_can_see_meeting(conn: psycopg.Connection, actor: Actor, meeting_id: str) -> bool:
    """A meeting they recorded, or one they were named in."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1 from meetings m
            where m.id = %(m)s
              and (m.logged_by = %(e)s
                   or exists (select 1 from meeting_attendees a
                              where a.meeting_id = m.id and a.employee_id = %(e)s))
            """,
            {"m": meeting_id, "e": actor.entity_id},
        )
        return cur.fetchone() is not None


def employee_can_see_entity(conn: psycopg.Connection, actor: Actor, entity_id: str) -> bool:
    """A customer they reach through a lead, a task, or a meeting of their own."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1 where exists (
                select 1 from leads l
                where l.entity_id = %(x)s and l.assigned_to = %(e)s
                union all
                select 1 from tasks t join task_assignees ta on ta.task_id = t.id
                where t.related_entity_id = %(x)s and ta.employee_id = %(e)s
                union all
                select 1 from meetings m
                where m.primary_contact_id = %(x)s
                  and (m.logged_by = %(e)s
                       or exists (select 1 from meeting_attendees a
                                  where a.meeting_id = m.id and a.employee_id = %(e)s))
            )
            """,
            {"x": entity_id, "e": actor.entity_id},
        )
        return cur.fetchone() is not None


def visible_meeting_clause(actor: Actor) -> tuple[str, dict]:
    """SQL fragment limiting meetings to the ones this person may read, for the
    history shown on a customer's page. Staff see everything; an employee must
    not read the owner's private notes from a visit they were not on."""
    if not actor.is_employee():
        return "true", {}
    return (
        "(m.logged_by = %(viewer)s or exists (select 1 from meeting_attendees a "
        " where a.meeting_id = m.id and a.employee_id = %(viewer)s))",
        {"viewer": actor.entity_id},
    )
