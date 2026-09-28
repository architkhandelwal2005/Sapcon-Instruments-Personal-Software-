"""A greeting costs nothing: no model call, no row, no reply.

Every case here is settled before the model would be asked, so none of them
touch the network - and none of them spend a call from a daily allowance that
a courtesy has no business spending.
"""

import pytest

from app.agent.plan import is_courtesy, plan_message


@pytest.mark.parametrize("text", [
    "thanks", "Thanks!", "thank you", "thank you so much",
    "ok", "Ok.", "okay", "got it", "noted", "understood",
    "hi", "Hello", "hey", "namaste", "good morning", "bye",
    "haan theek hai", "bilkul", "ji", "hmm", "achha",
    "yes", "sure", "perfect", "great", "cool", "all clear",
    "👍", "✓", "...", "!!",
])
def test_a_courtesy_needs_no_model_call(text):
    assert is_courtesy(text) is True
    plan = plan_message(text, "")          # would hit the network if it called out
    assert plan.action == "chat"
    assert plan.reply == ""                # saying nothing back is the point


@pytest.mark.parametrize("text", [
    "thanks, also met Rajesh today",
    "ok assign the Rakesh follow-up to Vishal",
    "hi, Parag Foods wants two level transmitters",
    "yes the quotation for Gujarat Ambuja went out on Monday",
    "Met Rajesh Sharma at Parag Foods today",
    "what is pending with Vishal",
])
def test_a_courtesy_wrapped_around_real_content_is_not_one(text):
    # Every word has to be a known courtesy. Dropping one of these would lose
    # a visit or ignore a question.
    assert is_courtesy(text) is False


def test_a_long_run_of_pleasant_words_is_still_not_a_courtesy():
    assert is_courtesy("thanks " * 20) is False
