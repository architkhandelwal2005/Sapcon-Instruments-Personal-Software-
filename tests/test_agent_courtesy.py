"""Pleasantries, settled without a model call.

Two kinds, wanting opposite treatment. A closer ends an exchange and answering
it only invites another "ok". A greeting starts one, and silence in answer to
"hi" reads as a dead number - which is how it read to the first person who
tried it.

None of these touch the network, and none spend a call from a daily allowance
that a pleasantry has no business spending.
"""

import pytest

from app.agent.plan import GREETING_REPLY, courtesy_reply, plan_message


@pytest.mark.parametrize("text", [
    "hi", "Hi!", "hii", "hello", "Hello.", "hey", "yo",
    "namaste", "namaskar", "good morning", "good evening",
])
def test_a_greeting_is_answered(text):
    assert courtesy_reply(text) == GREETING_REPLY
    plan = plan_message(text, "")          # would hit the network if it called out
    assert plan.action == "chat"
    assert plan.reply == GREETING_REPLY


def test_the_greeting_says_what_it_can_actually_do():
    for ability in ("voice note", "pending", "assign"):
        assert ability in GREETING_REPLY.lower()


@pytest.mark.parametrize("text", [
    "thanks", "Thanks!", "thank you", "thank you so much",
    "ok", "Ok.", "okay", "got it", "noted", "understood",
    "haan theek hai", "bilkul", "ji", "hmm", "achha",
    "yes", "sure", "perfect", "cool", "all clear", "bye",
    "👍", "✓", "...",
])
def test_a_closer_is_left_alone(text):
    assert courtesy_reply(text) == ""
    plan = plan_message(text, "")
    assert plan.action == "chat"
    assert plan.reply == ""


@pytest.mark.parametrize("text", [
    "thanks, also met Rajesh today",
    "ok assign the Rakesh follow-up to Vishal",
    "hi, Parag Foods wants two level transmitters",
    "hello can you tell me what is pending with Vishal",
    "yes the quotation for Gujarat Ambuja went out on Monday",
    "Met Rajesh Sharma at Parag Foods today",
    "what is pending with Vishal",
])
def test_a_pleasantry_wrapped_around_real_content_is_not_one(text):
    # Every word has to be known. Dropping one of these would lose a visit or
    # ignore a question.
    assert courtesy_reply(text) is None


def test_a_long_run_of_pleasant_words_is_not_a_pleasantry():
    assert courtesy_reply("thanks " * 20) is None
