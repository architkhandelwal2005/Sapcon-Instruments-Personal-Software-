"""Dropping the wrong lead.

"Drop Deccan Ceramics" found one open lead - a list row reading "NACL, SRF,
Meghmani, Thermax, Adani, Barthi Pama, Deccan Wader" - on the strength of the
word "Deccan" alone, and dropped it. One row matching is not the same as one
row being meant.
"""

import pytest

from app.commands.apply import _ambiguous, _is_weak, _words


def _rows(*names):
    return [(f"id{i}", n, n) for i, n in enumerate(names)]


def test_half_the_words_finding_nothing_is_a_weak_match():
    words = _words("Deccan Ceramics")
    rows = _rows("NACL, SRF, Meghmani, Thermax, Adani, Barthi Pama, Deccan Wader")
    assert _is_weak(rows, words) is True


def test_a_row_matching_both_words_is_not_weak():
    words = _words("Deccan Ceramics")
    assert _is_weak(_rows("Deccan Ceramics Pvt Ltd"), words) is False


def test_one_word_said_is_never_weak():
    """"Drop Meghmani" is all he said, so matching it is matching everything he
    gave - there is nothing partial about it."""
    assert _is_weak(_rows("Meghmani Industries"), _words("Meghmani")) is False


def test_a_longer_name_still_counts_when_most_of_it_lands():
    words = _words("Konkan Dairy Products")
    assert _is_weak(_rows("Konkan Dairy"), words) is False


def test_nothing_matching_is_not_reported_as_weak():
    # No rows at all is "not found", which is a different answer.
    assert _is_weak([], _words("Deccan Ceramics")) is False


def test_a_partial_single_match_reads_as_a_question_not_a_count():
    outcome = _ambiguous("drop_lead", "lead", [("id0", "Deccan Wader")], weak=True)
    assert outcome.status == "ambiguous"
    assert "partial match" in outcome.summary
    assert "1 open leads" not in outcome.summary


def test_several_matches_still_read_as_a_count():
    outcome = _ambiguous("drop_lead", "lead", [("a", "One"), ("b", "Two")])
    assert "2 open leads match that" in outcome.summary


@pytest.mark.parametrize("names", [("Deccan Wader",), ("Deccan Wader", "Deccan Traders")])
def test_a_weak_match_never_applies_itself(names):
    outcome = _ambiguous("drop_lead", "lead", [(f"id{i}", n) for i, n in enumerate(names)], weak=True)
    assert outcome.status != "applied"
    assert outcome.undo_token is None
