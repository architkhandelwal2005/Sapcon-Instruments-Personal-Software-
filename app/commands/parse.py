"""Read an instruction out of a sentence.

The model is asked only what the sender wants done and to whom, in the words
they used. It never picks a row - matching words to a particular task or lead is
done in SQL afterwards, where an ambiguous match can be counted and refused
rather than resolved by a guess.
"""

import re
from dataclasses import dataclass
from typing import Literal, Optional

from app.llm import complete_json

Action = Literal["assign_task", "complete_task", "drop_lead"]

# Most messages are notes, and asking a model "is this an instruction?" about
# every one of them would spend a large share of the free tier's daily calls on
# answers that are always no. An instruction has to contain one of these words,
# so a message without any is not one - cheap, and wrong only in the safe
# direction, since a missed command falls through to being logged as a note.
_COMMAND_WORDS = re.compile(
    r"\b("
    r"assign(s|ed|ing)?|reassign(ed|ing)?|allot(s|ted|ting)?|"
    r"hand(ed|s)?\s+over|give\s+it|should\s+handle|take\s+over|"
    r"done|complete[d]?|finish(ed)?|closed?|mark|sorted|"
    r"drop(ped|ping)?|dead|cancel(led)?|not\s+interested|no\s+longer"
    r")\b",
    re.IGNORECASE,
)


def looks_like_command(text: str) -> bool:
    """Whether this message is worth asking the model about."""
    return bool(_COMMAND_WORDS.search(text or ""))


_SYSTEM = """You read an instruction sent to a sales CRM and say what it asks to change.

Actions:
- "assign_task": give an existing task an owner. "assign the Rakesh follow-up to Vishal",
  "Vishal should handle the Parag quotation", "give the Thermo task to Saurabh".
- "complete_task": mark an existing task finished. "the Parag quotation is done",
  "mark the Rakesh follow-up complete", "we sent the brochure to Konkan".
- "drop_lead": stop pursuing a lead. "drop Meghmani", "Taga Incinerators is dead",
  "close the Kiritish Patel lead, not interested".

Return JSON:
{"action": "<one of the three, or null>",
 "target": "<the words naming the task or lead, copied from the message>",
 "person": "<the person it should go to, for assign_task only, else null>"}

Return {"action": null} when the message records something that happened, asks a
question, or asks for anything other than those three changes. Recording a NEW task
("tell Vishal to call him on Monday") is NOT a command - it is a note. A command
always refers to something that already exists."""


@dataclass
class ParsedCommand:
    action: Action
    target: str
    person: Optional[str] = None


def parse_command(text: str) -> Optional[ParsedCommand]:
    """The instruction in this message, or None when it is not one. Never
    raises: a failed call means "not a command", so the message falls through
    to being logged and nothing is lost."""
    body = (text or "").strip()
    if not body or not looks_like_command(body):
        return None
    try:
        raw = complete_json(_SYSTEM, body, max_tokens=200)
    except Exception:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return None

    action = (raw.get("action") or "").strip()
    target = (raw.get("target") or "").strip()
    if action not in ("assign_task", "complete_task", "drop_lead") or not target:
        return None

    person = (raw.get("person") or "").strip() or None
    if action == "assign_task" and not person:
        return None
    return ParsedCommand(action=action, target=target, person=person)
