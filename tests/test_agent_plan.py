"""The planner decides what a message wants. It never decides which record.

Every case here monkeypatches the model call, so no quota is spent and the
guards are tested rather than the model's taste.
"""

import pytest

from app.agent.plan import MAX_CHAT_CHARS, plan_message


def _patch(monkeypatch, answer):
    monkeypatch.setattr("app.agent.plan.complete_json", lambda *a, **k: answer)


def test_it_carries_the_senders_own_words_not_a_record(monkeypatch):
    _patch(monkeypatch, {"action": "assign_task", "target": "the Rakesh follow-up",
                         "person": "Vishal"})
    plan = plan_message("give the rakesh follow-up to vishal", "")
    assert plan.action == "assign_task"
    assert plan.target == "the Rakesh follow-up"      # words, not a task id
    assert plan.person == "Vishal"


def test_a_follow_up_question_is_rewritten_to_stand_alone(monkeypatch):
    _patch(monkeypatch, {"action": "ask", "question": "What is pending with Parag Foods?"})
    plan = plan_message("and Parag?", "Them: what is pending with Thermo\nYou: two tasks...")
    assert plan.action == "ask"
    assert plan.question == "What is pending with Parag Foods?"


def test_chat_carries_its_own_reply(monkeypatch):
    _patch(monkeypatch, {"action": "chat",
                         "reply": "I log visits, answer questions, and make changes."})
    plan = plan_message("what can you do", "")
    assert plan.action == "chat"
    assert "log visits" in plan.reply


def test_a_long_message_is_never_treated_as_chat(monkeypatch):
    """The guard that matters most. A long message answered with a pleasantry
    is a visit thrown away."""
    _patch(monkeypatch, {"action": "chat", "reply": "Sure!"})
    plan = plan_message("x" * (MAX_CHAT_CHARS + 1), "")
    assert plan.action == "log"


def test_a_change_with_nothing_to_match_on_is_filed_instead(monkeypatch):
    # No target means no way to find the row, and guessing one is the single
    # thing this must never do.
    _patch(monkeypatch, {"action": "complete_task", "target": ""})
    assert plan_message("mark it done", "").action == "log"


def test_assigning_to_nobody_is_filed_instead(monkeypatch):
    _patch(monkeypatch, {"action": "assign_task", "target": "the Rakesh task", "person": ""})
    assert plan_message("reassign the rakesh task", "").action == "log"


@pytest.mark.parametrize("answer", [
    None, [], "log", {"action": "banana"}, {"action": ""}, {},
])
def test_an_answer_that_makes_no_sense_falls_back_to_filing(monkeypatch, answer):
    _patch(monkeypatch, answer)
    assert plan_message("Met Rajesh at Parag today", "").action == "log"


def test_a_failed_model_call_files_the_message(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr("app.agent.plan.complete_json", boom)
    plan = plan_message("Met Rajesh at Parag today, they need two transmitters", "")
    assert plan.action == "log"


def test_an_empty_message_asks_for_nothing():
    # No model call at all - if one were made this would hit the network.
    plan = plan_message("   ", "")
    assert plan.action == "chat" and plan.reply == ""


def test_a_question_defaults_to_the_message_when_the_model_omits_it(monkeypatch):
    _patch(monkeypatch, {"action": "ask"})
    plan = plan_message("who is Priya Nair", "")
    assert plan.question == "who is Priya Nair"


def test_chat_with_nothing_to_say_still_says_something(monkeypatch):
    """Silence is a deliberate answer to "thanks" and never to anything else.
    "Whats left" got no reply at all, which reads exactly like a dead number."""
    from app.agent.plan import UNSURE_REPLY

    _patch(monkeypatch, {"action": "chat", "reply": ""})
    plan = plan_message("whats left", "")
    assert plan.action == "chat"
    assert plan.reply == UNSURE_REPLY


def test_the_unsure_reply_offers_something_to_try():
    from app.agent.plan import UNSURE_REPLY

    assert "pending" in UNSURE_REPLY and "voice note" in UNSURE_REPLY
