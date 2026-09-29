"""Deciding a question names somebody, when the spelling does not match.

"What's pending with Mokshil" found nothing and said so honestly, while Moksha
Shah sat in the database with three records against him. Names in questions
were matched verbatim - which asks him to reproduce a spelling that often came
from a mishearing in the first place.

The word-picking half is pure and tested here. The similarity half needs the
database and is exercised against the real one.
"""

import pytest

from app.query.nearby import _candidate_words


@pytest.mark.parametrize("question,expected", [
    ("whats pending with Mokshil", ["mokshil"]),
    ("what do we know about marmik", ["marmik"]),
    ("tell me about Kanika Chanda", ["kanika", "chanda"]),
    ("brief me on Gujarat Ambuja", ["gujarat", "ambuja"]),
])
def test_it_picks_out_the_words_that_could_be_a_name(question, expected):
    assert _candidate_words(question) == expected


@pytest.mark.parametrize("question", [
    "how many calls did we make",
    "what is overdue",
    "give me a summary of last week",
    "what happened yesterday",
    "anything pending",
    "show me the open tasks",
])
def test_an_ordinary_question_names_nobody(question):
    """"Make" matched ICE Make Refrigeration Limited and would have answered
    about that company. Only runs when nothing matched exactly, so a false
    positive sends a whole answer off course."""
    assert _candidate_words(question) == []


@pytest.mark.parametrize("word", ["ok", "abc", "a"])
def test_a_word_too_short_to_be_a_name_is_ignored(word):
    assert _candidate_words(f"what about {word}") == []


def test_punctuation_does_not_stick_to_a_name():
    assert _candidate_words("what about Mokshil?") == ["mokshil"]
    assert _candidate_words("Kanika, anything?") == ["kanika"]


def test_a_number_is_not_a_name():
    assert _candidate_words("what about 2026 targets") == []
