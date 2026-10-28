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

from app import history
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


def apply_command(conn: psycopg.Connection, command: ParsedCommand,
                  actor_id: Optional[str] = None) -> CommandOutcome:
    """`actor_id` is who sent the instruction, so the change log can say who
    made the change."""
    if command.action == "assign_task":
        return _assign_task(conn, command, actor_id)
    if command.action == "complete_task":
        return _complete_task(conn, command, actor_id)
    if command.action == "add_lead":
        return add_lead(conn, command, actor_id)
    return _drop_lead(conn, command, actor_id)


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


def _assign_task(conn: psycopg.Connection, command: ParsedCommand,
                 actor_id: Optional[str] = None) -> CommandOutcome:
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
    return assign_task_to(conn, task_id, employee_id, employee_name, label, actor_id)


def assign_task_to(conn: psycopg.Connection, task_id: str, employee_id: str,
                   employee_name: str, label: str, actor_id: Optional[str] = None) -> CommandOutcome:
    """Replaces the owners rather than adding one: "assign it to Vishal" means
    Vishal owns it, not that Vishal joins whoever had it."""
    owners = [{"employee_id": employee_id, "name": employee_name}]
    change_id = history.change(conn, "task", task_id, "owners", owners,
                               actor_id=actor_id, via="whatsapp")
    if change_id is None:
        conn.rollback()
        return CommandOutcome(status="already", action="assign_task", row_id=task_id,
                              url_path="/tasks",
                              summary=f"{employee_name} already owns \"{label}\".")
    conn.commit()
    return CommandOutcome(
        status="applied", action="assign_task", row_id=task_id, url_path="/tasks",
        summary=f"\"{label}\" is now {employee_name}'s.",
        undo_token=_token("assign_task", change_id),
    )


def _complete_task(conn: psycopg.Connection, command: ParsedCommand,
                   actor_id: Optional[str] = None) -> CommandOutcome:
    found = _find_tasks(conn, command.target)
    if not found:
        return CommandOutcome(status="not_found", action=command.action,
                              summary=f"No open task matches \"{command.target}\".")
    if len(found) > 1:
        return _ambiguous(command.action, "task", found)

    task_id, label = found[0]
    return complete_task(conn, task_id, label, actor_id)


def complete_task(conn: psycopg.Connection, task_id: str, label: str,
                  actor_id: Optional[str] = None) -> CommandOutcome:
    change_id = history.change(conn, "task", task_id, "status", "done",
                               actor_id=actor_id, via="whatsapp")
    if change_id is None:
        exists = _exists(conn, "tasks", task_id)
        conn.rollback()
        if not exists:
            return CommandOutcome(status="not_found", action="complete_task",
                                  summary="That task no longer exists.")
        return CommandOutcome(status="already", action="complete_task", row_id=task_id,
                              summary=f"\"{label}\" is already done.")
    conn.commit()
    return CommandOutcome(
        status="applied", action="complete_task", row_id=task_id, url_path="/tasks",
        summary=f"\"{label}\" is marked done.",
        undo_token=_token("complete_task", change_id),
    )


def _drop_lead(conn: psycopg.Connection, command: ParsedCommand,
               actor_id: Optional[str] = None) -> CommandOutcome:
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
    return drop_lead(conn, lead_id, name, actor_id)


def drop_lead(conn: psycopg.Connection, lead_id: str, name: str,
              actor_id: Optional[str] = None) -> CommandOutcome:
    """Dropping is a status change, never a delete - the lead keeps its history
    and can be reopened, the same rule the rest of the system follows."""
    change_id = history.change(conn, "lead", lead_id, "status", "dropped",
                               actor_id=actor_id, via="whatsapp")
    if change_id is None:
        exists = _exists(conn, "leads", lead_id)
        conn.rollback()
        if not exists:
            return CommandOutcome(status="not_found", action="drop_lead",
                                  summary="That lead no longer exists.")
        return CommandOutcome(status="already", action="drop_lead", row_id=lead_id,
                              summary=f"Lead \"{name}\" is already dropped.")
    conn.commit()
    return CommandOutcome(
        status="applied", action="drop_lead", row_id=lead_id, url_path=f"/leads/{lead_id}",
        summary=f"Lead \"{name}\" is dropped - it keeps its history and can be reopened.",
        undo_token=_token("drop_lead", change_id),
    )


def _find_customers(conn: psycopg.Connection, target: str) -> tuple:
    """Companies and people, never our own staff, by the words he used."""
    words = _words(target)
    if not words:
        return [], False
    any_clause = " or ".join(
        f"(e.canonical_name ilike %(w{i})s or array_to_string(e.aliases, ' ') ilike %(w{i})s)"
        for i in range(len(words)))
    params = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select e.id, e.canonical_name, e.canonical_name || ' ' || array_to_string(e.aliases, ' ')
            from entities e
            where e.entity_type in ('company', 'person') and e.review_status <> 'rejected'
              and e.merged_into is null and ({any_clause})
            limit 25
            """,
            params,
        )
        rows = [(str(i), n, h) for i, n, h in cur.fetchall()]
    return _best_matches(rows, words), _is_weak(rows, words)


def add_lead(conn: psycopg.Connection, command: ParsedCommand,
             actor_id: Optional[str] = None) -> CommandOutcome:
    """"Make Parag Dairy a lead for Vishal." A lead is made only when he says
    so - a company mentioned in a note is not a lead until someone decides it
    is worth chasing. A name that matches nothing becomes a new company, marked
    for review; one that matches several is asked about, never guessed."""
    owner = None
    if (command.person or "").strip():
        owner = find_employee_by_spoken_name(conn, command.person)
        if owner is None:
            return CommandOutcome(status="no_person", action="add_lead",
                                  summary=f"I could not find \"{command.person}\" on the team. Nothing was added.")

    found, weak = _find_customers(conn, command.target)
    if weak:
        # Only part of the name matched anything - "Brandnew Agro" against
        # every company with "Agro" in it. That is a new name, not a choice
        # between old ones. It is created for review, where a real duplicate
        # is caught and merged.
        found = []
    if len(found) > 1:
        names = ", ".join(label for _, label in found[:5])
        return CommandOutcome(status="not_found", action="add_lead",
                              summary=f"More than one contact could be \"{command.target}\": {names}. "
                                      "Say the full name and I will add it.")
    with conn.cursor() as cur:
        if found:
            entity_id, name = found[0]
            cur.execute("select l.id, ae.canonical_name from leads l "
                        "left join entities ae on ae.id = l.assigned_to "
                        "where l.entity_id = %s and l.status = 'open'", (entity_id,))
            open_lead = cur.fetchone()
            if open_lead:
                who = f", with {open_lead[1]}" if open_lead[1] else ", not given to anyone yet"
                return CommandOutcome(status="already", action="add_lead", row_id=str(open_lead[0]),
                                      url_path=f"/leads/{open_lead[0]}",
                                      summary=f"{name} is already an open lead{who}.")
        else:
            name = " ".join(w.capitalize() if w.islower() else w for w in command.target.split())
            cur.execute(
                "insert into entities (canonical_name, entity_type, source, review_status) "
                "values (%s, 'company', 'whatsapp', 'pending') returning id", (name,))
            entity_id = str(cur.fetchone()[0])
        cur.execute(
            "insert into leads (entity_id, assigned_to, source) values (%s, %s, 'whatsapp') returning id",
            (entity_id, owner[0] if owner else None))
        lead_id = str(cur.fetchone()[0])
    conn.commit()
    for_whom = f" for {owner[1]} - they have been told" if owner else " - not given to anyone yet"
    new = "" if found else " (new contact, added for review)"
    return CommandOutcome(status="applied", action="add_lead", row_id=lead_id,
                          url_path=f"/leads/{lead_id}",
                          summary=f"Added {name}{new} as a lead{for_whom}.")


def _exists(conn: psycopg.Connection, table: str, row_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"select 1 from {table} where id = %s", (row_id,))
        return cur.fetchone() is not None


# --------------------------------------------------------------------------
# undo


def _token(action: str, change_id: int) -> str:
    return json.dumps({"action": action, "change_ids": [change_id]})


_UNDONE = {
    "assign_task": "Put the task's owner back.",
    "complete_task": "The task is open again.",
    "drop_lead": "The lead is back to open.",
}


def undo_command(conn: psycopg.Connection, token: str,
                 actor_id: Optional[str] = None) -> CommandOutcome:
    """Put a change back, through the same change log the website uses.

    It used to restore the recorded previous state unconditionally, which
    overwrote anything done in between: undo "marked done" after someone else
    had reassigned the task, and their reassignment went too. Now an undo is
    refused when the row has moved on, and says so.

    The token itself is the authority - it was sent only to the person who made
    the change, and only they can reply to it - so ownership is not rechecked.
    """
    try:
        data = json.loads(token)
        action, change_ids = data["action"], data["change_ids"]
    except (ValueError, KeyError, TypeError):
        return CommandOutcome(status="not_found", action="undo", summary="Nothing to undo.")

    for change_id in change_ids:
        outcome = history.undo(conn, change_id, actor_id=actor_id, may_undo_others=True)
        if outcome != "done":
            conn.rollback()
            return CommandOutcome(status="not_found", action="undo",
                                  summary=history.UNDO_WORDS[outcome])
    conn.commit()
    return CommandOutcome(status="applied", action="undo",
                          summary=_UNDONE.get(action, history.UNDO_WORDS["done"]))
