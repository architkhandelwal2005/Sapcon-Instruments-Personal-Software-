"""Three answers, not two. A greeting is not a meeting.

The word-list half of this runs with no model call at all, so these tests hit
no network: every case here is settled before the model would be asked.
"""

import pytest

from app.whatsapp.intent import MAX_NOTHING_CHARS, classify, is_acknowledgement


@pytest.mark.parametrize("text", [
    "thanks", "Thanks!", "thank you", "ok", "Ok.", "okay", "got it", "noted",
    "hi", "Hello", "hey", "namaste", "good morning", "bye",
    "haan theek hai", "bilkul", "ji", "hmm",
    "yes", "sure", "perfect", "great", "cool",
    "👍", "✓", "...", "!!",
])
def test_a_courtesy_is_settled_without_a_model_call(text):
    assert is_acknowledgement(text) is True
    assert classify(text) == "nothing"


@pytest.mark.parametrize("text", [
    "thanks, also met Rajesh today",
    "ok assign the Rakesh follow-up to Vishal",
    "hi, Parag Foods wants two level transmitters",
    "yes the quotation for Gujarat Ambuja went out on Monday",
])
def test_a_courtesy_wrapped_around_real_content_is_not_one(text):
    # Every word has to be a known courtesy, so these fall through to the model
    # and are filed. Dropping one of these would lose a visit.
    assert is_acknowledgement(text) is False


@pytest.mark.parametrize("text", [
    "Met Rajesh Sharma at Parag Foods today, they need two level transmitters",
    "what is pending with Vishal",
])
def test_a_real_message_is_never_an_acknowledgement(text):
    assert is_acknowledgement(text) is False


def test_an_empty_message_is_nothing():
    assert classify("") == "nothing"
    assert classify("   ") == "nothing"


def test_a_long_message_is_never_discarded(monkeypatch):
    """The guard that matters: however sure the model is that a message is
    small talk, a long one is filed. A long message thrown away is a visit
    gone; a long acknowledgement is not a thing people send."""
    monkeypatch.setattr("app.whatsapp.intent.complete_json",
                        lambda *a, **k: {"kind": "nothing"})
    long_message = "x" * (MAX_NOTHING_CHARS + 1)
    assert classify(long_message) == "note"


def test_a_short_message_the_model_calls_small_talk_is_dropped(monkeypatch):
    monkeypatch.setattr("app.whatsapp.intent.complete_json",
                        lambda *a, **k: {"kind": "nothing"})
    assert classify("great, will do") == "nothing"


def test_a_failed_model_call_files_the_message(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("503 UNAVAILABLE")

    monkeypatch.setattr("app.whatsapp.intent.complete_json", boom)
    assert classify("some message the model never saw") == "note"


@pytest.mark.parametrize("answer", [None, [], "note", {"kind": "banana"}])
def test_an_answer_that_makes_no_sense_files_the_message(monkeypatch, answer):
    monkeypatch.setattr("app.whatsapp.intent.complete_json", lambda *a, **k: answer)
    assert classify("some message") == "note"
