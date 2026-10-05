"""Find the row an instruction means, and change it - or refuse.

Matching is done here in SQL rather than by the model, so that "the Rakesh
task" matching two open tasks is a countable fact and not something a model
resolves by picking one. Several matches means the command is not applied and
the candidates are handed back for a person to choose from.

Every change returns an undo token that puts the row back exactly as it was.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

import psycopg

from app.commands.parse import ParsedCommand
from app.entity_resolution.employees import find_employee_by_spoken_name
from app.hinglish import FUNCTION_WORDS

Status = Literal["applied", "ambiguous", "not_found", "no_person", "already"]


@dataclass
class Candidate:
    row_id: str
    label: str


@dataclass
class CommandOutcome:
    status: Status
    action: str
    summary: str = ""                       # what changed, in words
    row_id: Optional[str] = None
    url_path: Optional[str] = None
    candidates: list[Candidate] = field(default_factory=list)
    undo_token: Optional[str] = None        # put it back exactly


def apply_command(conn: psycopg.Connection, command: ParsedCommand) -> CommandOutcome:
    if command.action == "assign_task":
        return _assign_task(conn, command)
    if command.action == "complete_task":
        return _complete_task(conn, command)
    return _drop_lead(conn, command)


# --------------------------------------------------------------------------
# finding the row


# People name a task loosely - "the Rakesh task", "the scope document one" -
# and these words carry no information about which row is meant.
_FILLER = {
    "task", "tasks", "item", "thing", "one", "lead", "leads", "follow", "followup",
    "follow-up", "the", "that", "this", "for", "with", "and", "about", "from",
} | FUNCTION_WORDS
# Without the Hindi, this is where a clear instruction got refused. Scoring
# keeps a match only if it covers 60% of the meaningful words, and "Rajesh wala
# task band kar do" offered four - three of them grammar that no English task
# description contains. One honest hit on "rajesh" read as a partial match, so
# the instruction was turned down while "Rajesh task" was carried out.


def _words(target: str) -> list[str]:
    cleaned = (target or "").replace("-", " ").lower()
    return [w for w in cleaned.split() if len(w) > 2 and w not in _FILLER]


def _best_matches(rows: list[tuple[str, str, str]], words: list[str]) -> list[tuple[str, str]]:
    """The rows matching the most of the words that carry meaning.

    Matching every word would miss "the Rakesh task" (no row says "task") and
    matching any would return everything Rakesh touches. Scoring and keeping
    only the best tier does both: an exact phrase narrows to one row, while a
    loose phrase returns the few rows that tie, which the caller then offers as
    a numbered choice rather than guessing between them.
    """
    scored = []
    for row_id, label, haystack in rows:
        hits = sum(1 for w in words if w in haystack.lower())
        if hits:
            scored.append((hits, row_id, label))
    if not scored:
        return []
    best = max(h for h, _, _ in scored)
    return [(row_id, label) for hits, row_id, label in scored if hits == best]


# Below this share of the words he said, the row that came back is a
# coincidence rather than a choice. Two-thirds keeps "Konkan Dairy" for "Konkan
# Dairy Products" and rejects "Deccan Wader" for "Deccan Ceramics".
_ENOUGH_OF_THE_WORDS = 0.6


def _is_weak(rows: list[tuple[str, str, str]], words: list[str]) -> bool:
    """True when the best row matched only part of what he said.

    "Drop Deccan Ceramics" found one open lead - a list row reading "NACL, SRF,
    Meghmani, Thermax, Adani, Barthi Pama, Deccan Wader" - on the strength of
    the word "Deccan" alone, and dropped it. One row matching is not the same
    as one row being meant.

    No rows at all is not weak: that is "found nothing", a different answer
    with a different reply."""
    if len(words) < 2 or not rows:
        return False
    best = max(sum(1 for w in words if w in h.lower()) for _, _, h in rows)
    return best < len(words) * _ENOUGH_OF_THE_WORDS


def _find_tasks(conn: psycopg.Connection, target: str, *, open_only: bool = True) -> list[tuple[str, str]]:
    """Open tasks whose text, or whose customer's name, matches the words used."""
    words = _words(target)
    if not words:
        return []
    any_clause = " or ".join(
        f"(t.description ilike %(w{i})s or re.canonical_name ilike %(w{i})s)" for i in range(len(words))
    )
    params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select t.id, t.description, re.canonical_name
            from tasks t
            left join entities re on re.id = t.related_entity_id
            where t.review_status <> 'rejected'
              {"and t.status = 'open'" if open_only else ""}
              and ({any_clause})
            order by t.due_date nulls last
            limit 25
            """,
            params,
        )
        rows = [(str(tid), desc + (f" (about {about})" if about else ""), f"{desc} {about or ''}")
                for tid, desc, about in cur.fetchall()]
    return _best_matches(rows, words)


def _find_leads(conn: psycopg.Connection, target: str) -> tuple:
    """(matches, weak). `weak` means the best row matched only part of what he
    said, so one survivor is a coincidence rather than a choice."""
    words = _words(target)
    if not words:
        return [], False
    any_clause = " or ".join(f"e.canonical_name ilike %(w{i})s" for i in range(len(words)))
    params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select l.id, e.canonical_name
            from leads l join entities e on e.id = l.entity_id
            where l.status = 'open' and ({any_clause})
            order by l.created_at desc
            limit 25
            """,
            params,
        )
        rows = [(str(lid), name, name) for lid, name in cur.fetchall()]
    return _best_matches(rows, words), _is_weak(rows, words)


def _ambiguous(action: str, what: str, found: list[tuple[str, str]],
               *, weak: bool = False) -> CommandOutcome:
    if weak and len(found) == 1:
        # Saying "1 open leads match that" reads like a bug and hides the real
        # point, which is that only part of what he said was found.
        summary = f"Only a partial match for that - is this the {what} you mean?"
    else:
        summary = f"{len(found)} open {what}{'s' if len(found) != 1 else ''} match that."
    return CommandOutcome(
        status="ambiguous", action=action, summary=summary,
        candidates=[Candidate(row_id=rid, label=label) for rid, label in found],
    )


# --------------------------------------------------------------------------
# the three changes


def _assign_task(conn: psycopg.Connection, command: ParsedCommand) -> CommandOutcome:
    employee = find_employee_by_spoken_name(conn, command.person or "")
    if employee is None:
        return CommandOutcome(status="no_person", action=command.action,
                              summary=f"Nobody on the team matches \"{command.person}\".")
    employee_id, employee_name = employee

    found = _find_tasks(conn, command.target)
    if not found:
        return CommandOutcome(status="not_found", action=command.action,
                              summary=f"No open task matches \"{command.target}\".")
    if len(found) > 1:
        return _ambiguous(command.action, "task", found)

    task_id, label = found[0]
    return assign_task_to(conn, task_id, employee_id, employee_name, label)


def assign_task_to(conn: psycopg.Connection, task_id: str, employee_id: str,
                   employee_name: str, label: str) -> CommandOutcome:
    """Replaces the owners rather than adding one: "assign it to Vishal" means
    Vishal owns it, not that Vishal joins whoever had it."""
    with conn.cursor() as cur:
        cur.execute(
            "select coalesce(employee_id::text, ''), name from task_assignees where task_id = %s",
            (task_id,),
        )
        before = [{"employee_id": eid or None, "name": name} for eid, name in cur.fetchall()]
        if len(before) == 1 and before[0]["employee_id"] == employee_id:
            return CommandOutcome(status="already", action="assign_task", row_id=task_id,
                                  url_path="/tasks",
                                  summary=f"{employee_name} already owns \"{label}\".")
        cur.execute("delete from task_assignees where task_id = %s", (task_id,))
        cur.execute(
            "insert into task_assignees (task_id, name, employee_id) values (%s, %s, %s)",
            (task_id, employee_name, employee_id),
        )
    conn.commit()
    return CommandOutcome(
        status="applied", action="assign_task", row_id=task_id, url_path="/tasks",
        summary=f"\"{label}\" is now {employee_name}'s.",
        undo_token=_token("assign_task", task_id, {"assignees": before}),
    )


def _complete_task(conn: psycopg.Connection, command: ParsedCommand) -> CommandOutcome:
    found = _find_tasks(conn, command.target)
    if not found:
        return CommandOutcome(status="not_found", action=command.action,
                              summary=f"No open task matches \"{command.target}\".")
    if len(found) > 1:
        return _ambiguous(command.action, "task", found)

    task_id, label = found[0]
    return complete_task(conn, task_id, label)


def complete_task(conn: psycopg.Connection, task_id: str, label: str) -> CommandOutcome:
    with conn.cursor() as cur:
        cur.execute("update tasks set status = 'done' where id = %s returning status", (task_id,))
        if cur.fetchone() is None:
            conn.rollback()
            return CommandOutcome(status="not_found", action="complete_task",
                                  summary="That task no longer exists.")
    conn.commit()
    return CommandOutcome(
        status="applied", action="complete_task", row_id=task_id, url_path="/tasks",
        summary=f"\"{label}\" is marked done.",
        undo_token=_token("complete_task", task_id, {"status": "open"}),
    )


def _drop_lead(conn: psycopg.Connection, command: ParsedCommand) -> CommandOutcome:
    found, weak = _find_leads(conn, command.target)
    if not found:
        return CommandOutcome(status="not_found", action=command.action,
                              summary=f"No open lead matches \"{command.target}\".")
    # A partial match is offered rather than applied, even when only one row
    # came back. Dropping is the one change here that is about a customer
    # relationship rather than a line of work, and "Deccan Ceramics" quietly
    # dropping a row that merely contains the word "Deccan" is the kind of
    # mistake nobody notices until the customer calls.
    if len(found) > 1 or weak:
        return _ambiguous(command.action, "lead", found, weak=weak)

    lead_id, name = found[0]
    return drop_lead(conn, lead_id, name)


def drop_lead(conn: psycopg.Connection, lead_id: str, name: str,
              actor_id: Optional[str] = None) -> CommandOutcome:
    """Dropping is a status change, never a delete - the lead keeps its history
    and can be reopened, the same rule the rest of the system follows."""
    with conn.cursor() as cur:
        cur.execute("select status from leads where id = %s", (lead_id,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return CommandOutcome(status="not_found", action="drop_lead",
                                  summary="That lead no longer exists.")
        cur.execute(
            "update leads set status = 'dropped', status_changed_at = now(), status_changed_by = %s "
            "where id = %s",
            (actor_id, lead_id),
        )
    conn.commit()
    return CommandOutcome(
        status="applied", action="drop_lead", row_id=lead_id, url_path=f"/leads/{lead_id}",
        summary=f"Lead \"{name}\" is dropped - it keeps its history and can be reopened.",
        undo_token=_token("drop_lead", lead_id, {"status": row[0]}),
    )


# --------------------------------------------------------------------------
# undo


def _token(action: str, row_id: str, before: dict) -> str:
    return json.dumps({"action": action, "row_id": row_id, "before": before}, default=str)


def undo_command(conn: psycopg.Connection, token: str) -> CommandOutcome:
    """Put a row back the way it was. Reads only the recorded previous state,
    so an undo cannot itself pick the wrong row."""
    try:
        data = json.loads(token)
        action, row_id, before = data["action"], data["row_id"], data["before"]
    except (ValueError, KeyError, TypeError):
        return CommandOutcome(status="not_found", action="undo", summary="Nothing to undo.")

    with conn.cursor() as cur:
        if action == "assign_task":
            cur.execute("delete from task_assignees where task_id = %s", (row_id,))
            for owner in before.get("assignees", []):
                cur.execute(
                    "insert into task_assignees (task_id, name, employee_id) values (%s, %s, %s)",
                    (row_id, owner["name"], owner["employee_id"]),
                )
            summary = "Put the task's owner back."
        elif action == "complete_task":
            cur.execute("update tasks set status = %s where id = %s", (before["status"], row_id))
            summary = "The task is open again."
        elif action == "drop_lead":
            cur.execute(
                "update leads set status = %s, status_changed_at = now() where id = %s",
                (before["status"], row_id),
            )
            summary = "The lead is back to open."
        else:
            conn.rollback()
            return CommandOutcome(status="not_found", action="undo", summary="Nothing to undo.")
    conn.commit()
    return CommandOutcome(status="applied", action="undo", row_id=row_id, summary=summary)
