"""Carrying out an instruction sent on WhatsApp, and saying what changed.

The hard part is not making the change - it is refusing to make the wrong one.
When the words match several open tasks, the reply is a numbered list and the
change waits for a person to pick. The list is remembered against the message
it was sent as, so answering "2" is unambiguous even after other messages.

Every applied change offers an undo, because a wrong change noticed a minute
later should cost one word, not a trip to the website.
"""

import json
from typing import Optional

import psycopg

from app.commands import CommandOutcome, ParsedCommand, apply_command, undo_command
from app.commands.apply import (
    Candidate,
    assign_task_to,
    complete_task,
    drop_lead,
)
from app.entity_resolution.employees import find_employee_by_spoken_name

MAX_CHOICES = 5


def remember(conn: psycopg.Connection, wa_message_id: str, sender_phone: str,
             kind: str, payload: dict) -> None:
    """What this message is waiting for, so a short reply to it makes sense."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into whatsapp_pending (wa_message_id, sender_phone, kind, payload) "
                "values (%s, %s, %s, %s) on conflict (wa_message_id) do nothing",
                (wa_message_id, sender_phone, kind, json.dumps(payload)),
            )
        conn.commit()
    except Exception:
        conn.rollback()  # losing this costs a follow-up, never a change


def pending_for(conn: psycopg.Connection, wa_message_id: Optional[str]) -> Optional[dict]:
    if not wa_message_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "select kind, payload from whatsapp_pending where wa_message_id = %s",
            (wa_message_id,),
        )
        row = cur.fetchone()
    return {"kind": row[0], "payload": row[1]} if row else None


def command_reply(outcome: CommandOutcome, base_url: str) -> str:
    """What to send back. An applied change names what changed and how to undo
    it; a refusal says why and changes nothing."""
    if outcome.status == "applied":
        lines = [outcome.summary]
        if outcome.undo_token:
            lines.append("Reply \"undo\" to this message to put it back.")
        if outcome.url_path:
            lines.append(f"{base_url}{outcome.url_path}")
        return "\n".join(lines)

    if outcome.status == "ambiguous":
        lines = [outcome.summary, "Reply with the number:"]
        lines += [f"{i}. {c.label}" for i, c in enumerate(outcome.candidates[:MAX_CHOICES], start=1)]
        if len(outcome.candidates) > MAX_CHOICES:
            lines.append(f"(+{len(outcome.candidates) - MAX_CHOICES} more - say it more precisely)")
        return "\n".join(lines)

    # not_found, no_person, already - nothing changed, and the reason is the message
    return outcome.summary


def choice_payload(command: ParsedCommand, outcome: CommandOutcome) -> dict:
    return {
        "action": command.action,
        "person": command.person,
        "candidates": [{"row_id": c.row_id, "label": c.label}
                       for c in outcome.candidates[:MAX_CHOICES]],
    }


def parse_choice(text: str, count: int) -> Optional[int]:
    """The number someone replied with, as an index. "2", "2." and "number 2"
    all count; anything else is not a choice and is handled as a new message."""
    body = (text or "").strip().lower().removeprefix("number").strip().rstrip(".")
    if not body.isdigit():
        return None
    picked = int(body)
    return picked - 1 if 1 <= picked <= count else None


def apply_choice(conn: psycopg.Connection, payload: dict, index: int) -> CommandOutcome:
    """Carry out the instruction on the row that was picked."""
    chosen = payload["candidates"][index]
    row_id, label = chosen["row_id"], chosen["label"]
    action = payload["action"]

    if action == "assign_task":
        employee = find_employee_by_spoken_name(conn, payload.get("person") or "")
        if employee is None:
            return CommandOutcome(status="no_person", action=action,
                                  summary=f"Nobody on the team matches \"{payload.get('person')}\".")
        return assign_task_to(conn, row_id, employee[0], employee[1], label)
    if action == "complete_task":
        return complete_task(conn, row_id, label)
    return drop_lead(conn, row_id, label)


def is_undo(text: str) -> bool:
    return (text or "").strip().lower().rstrip(".!") in ("undo", "undo it", "revert", "cancel that")


__all__ = [
    "Candidate",
    "apply_choice",
    "apply_command",
    "choice_payload",
    "command_reply",
    "is_undo",
    "parse_choice",
    "pending_for",
    "remember",
    "undo_command",
]
