"""Instructions sent on WhatsApp. The rule that matters: a command that would
change the wrong row must change nothing at all."""

import pytest

from app.commands.parse import looks_like_command, parse_command
from app.commands.apply import Candidate, CommandOutcome
from app.whatsapp.commands import choice_payload, command_reply, is_undo, parse_choice
from app.commands import ParsedCommand

BASE = "https://crm.example.com"


@pytest.mark.parametrize("text", [
    "assign rakesh sharma to vishal",
    "reassign the Thermo follow-up to Saurabh",
    "Vishal should handle the Parag quotation",
    "the parag quotation is done",
    "mark the Rakesh follow-up complete",
    "drop Meghmani",
    "Taga Incinerators is dead",
    "close the Kiritish Patel lead, not interested",
])
def test_an_instruction_is_worth_asking_the_model_about(text):
    assert looks_like_command(text) is True


@pytest.mark.parametrize("text", [
    "Met Rajesh Sharma at Parag Foods today, they need two level transmitters",
    "what is pending with Vishal",
    "brief me on Gujarat Ambuja",
    "give me Rajesh's number",
])
def test_a_note_or_a_question_never_pays_for_the_extra_call(text):
    assert looks_like_command(text) is False


def test_a_message_with_no_command_word_is_not_a_command_without_calling_the_model():
    # If the model were called here the test would hit the network.
    assert parse_command("Met Rajesh at Parag today, they need two transmitters") is None


def test_an_applied_change_says_what_changed_and_how_to_undo_it():
    outcome = CommandOutcome(status="applied", action="assign_task", row_id="t1",
                             url_path="/tasks", summary='"Follow up with Rakesh" is now Vishal Dixit\'s.',
                             undo_token='{"action":"assign_task"}')
    reply = command_reply(outcome, BASE)
    assert "is now Vishal Dixit's" in reply
    assert "undo" in reply.lower()
    assert f"{BASE}/tasks" in reply


def test_an_ambiguous_command_offers_a_numbered_choice_and_changes_nothing():
    outcome = CommandOutcome(
        status="ambiguous", action="assign_task", summary="2 open tasks match that.",
        candidates=[Candidate("t1", "Follow up with Rakesh for the scope document"),
                    Candidate("t2", "Confirm with Rakesh if Thermo is the OEM")],
    )
    reply = command_reply(outcome, BASE)
    assert "1. Follow up with Rakesh" in reply
    assert "2. Confirm with Rakesh" in reply
    assert "undo" not in reply.lower()      # nothing was changed


def test_a_long_list_of_matches_asks_for_a_narrower_instruction():
    outcome = CommandOutcome(status="ambiguous", action="complete_task", summary="8 open tasks match that.",
                             candidates=[Candidate(f"t{i}", f"Task {i}") for i in range(8)])
    reply = command_reply(outcome, BASE)
    assert "+3 more" in reply


@pytest.mark.parametrize("status,expected", [
    ("not_found", "No open task matches"),
    ("no_person", "Nobody on the team"),
    ("already", "already owns"),
])
def test_a_refusal_explains_itself_and_offers_no_undo(status, expected):
    outcome = CommandOutcome(status=status, action="assign_task", summary=f"{expected} something.")
    reply = command_reply(outcome, BASE)
    assert expected in reply
    assert "undo" not in reply.lower()


@pytest.mark.parametrize("text,expected", [
    ("2", 1), ("1", 0), ("2.", 1), ("number 2", 1), (" 3 ", 2),
])
def test_a_numbered_reply_picks_that_choice(text, expected):
    assert parse_choice(text, 3) == expected


@pytest.mark.parametrize("text", ["", "yes", "the first one", "0", "4", "assign it to Vishal"])
def test_anything_that_is_not_a_number_in_range_is_not_a_choice(text):
    # It falls through and is handled as a fresh message, so a real instruction
    # sent while a question is open is not swallowed.
    assert parse_choice(text, 3) is None


@pytest.mark.parametrize("text", ["undo", "Undo", "undo it", "revert", "cancel that", "undo."])
def test_undo_is_recognised_however_it_is_written(text):
    assert is_undo(text) is True


@pytest.mark.parametrize("text", ["undo the Rakesh assignment", "no", "", "redo"])
def test_only_a_bare_undo_counts(text):
    assert is_undo(text) is False


def test_the_choice_it_remembers_carries_the_person_the_task_is_for():
    command = ParsedCommand(action="assign_task", target="Rakesh", person="Vishal")
    outcome = CommandOutcome(status="ambiguous", action="assign_task",
                             candidates=[Candidate("t1", "one"), Candidate("t2", "two")])
    payload = choice_payload(command, outcome)
    assert payload["person"] == "Vishal"
    assert [c["row_id"] for c in payload["candidates"]] == ["t1", "t2"]
