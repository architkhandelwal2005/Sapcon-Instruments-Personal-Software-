"""Changing something, as opposed to recording or asking about it.

WhatsApp intake could log a note and answer a question, but had no way to act.
So "assign Rakesh Sharma to Vishal" was filed as a fact - it created a task
called "Assign Rakesh Sharma task to Vishal" and left the real Rakesh task
sitting unowned, which is the opposite of what was asked.

Three things can be changed, chosen because they are the ones he says out loud:
give a task an owner, mark a task done, drop a lead.

Two rules hold everywhere here, because a command that changes the wrong row is
worse than one that changes nothing:

- Nothing is guessed. When the words match several open tasks - and "the Rakesh
  task" really did match two - the command is not applied. The candidates come
  back so a person picks.
- Every change is reversible and says how. The reply names what changed, and an
  undo token puts it back exactly.
"""

from app.commands.apply import CommandOutcome, apply_command, undo_command
from app.commands.parse import ParsedCommand, parse_command

__all__ = [
    "CommandOutcome",
    "ParsedCommand",
    "apply_command",
    "parse_command",
    "undo_command",
]
