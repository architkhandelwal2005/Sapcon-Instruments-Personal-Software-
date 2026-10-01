"""Deciding every name in a note with one call.

A note naming eight people spent eight model calls in a few seconds and ran the
per-minute quota out by itself. Batching them is only safe because a bad answer
is thrown away rather than acted on: the worst it can do is cost the calls it
was meant to save.
"""

from dataclasses import dataclass, field

import pytest

from app.entity_resolution.batch import MAX_PER_CALL, decide_many


@dataclass
class _Candidate:
    id: str
    canonical_name: str
    entity_type: str = "person"
    aliases: list = field(default_factory=list)
    title: str = ""
    region: str = ""


RAJESH = _Candidate("r1", "Rajesh Sharma")
PRIYA = _Candidate("p1", "Priya Nair")
ITEMS = [("Rajesh", "person", [RAJESH]), ("Priya", "person", [PRIYA])]


def _answer(monkeypatch, payload):
    monkeypatch.setattr("app.entity_resolution.batch.complete_json", lambda *a, **k: payload)


def test_each_name_gets_its_own_decision(monkeypatch):
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Rajesh", "decision": "match", "match_id": "r1", "confidence": "high"},
        {"mentioned": "Priya", "decision": "match", "match_id": "p1", "confidence": "high"},
    ]})
    out = decide_many(ITEMS, "a note")
    assert out["Rajesh"].match_id == "r1"
    assert out["Priya"].match_id == "p1"


def test_an_id_from_another_names_shortlist_is_refused(monkeypatch):
    """The failure that would matter: answering about the wrong person. Priya's
    id offered for Rajesh becomes "uncertain", which creates a flagged record
    instead of merging two customers."""
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Rajesh", "decision": "match", "match_id": "p1", "confidence": "high"},
    ]})
    out = decide_many(ITEMS, "a note")
    assert out["Rajesh"].decision == "uncertain"
    assert out["Rajesh"].match_id is None


def test_an_invented_id_is_refused(monkeypatch):
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Rajesh", "decision": "match", "match_id": "nonsense", "confidence": "high"},
    ]})
    assert decide_many(ITEMS, "a note")["Rajesh"].decision == "uncertain"


def test_a_name_nobody_asked_about_is_ignored(monkeypatch):
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Somebody Else", "decision": "match", "match_id": "r1", "confidence": "high"},
    ]})
    assert decide_many(ITEMS, "a note") == {}


def test_a_name_left_unanswered_is_simply_absent(monkeypatch):
    """Absent means "decide this one on its own" - never "treat it as new"."""
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Rajesh", "decision": "new", "match_id": None, "confidence": "high"},
    ]})
    out = decide_many(ITEMS, "a note")
    assert "Rajesh" in out and "Priya" not in out


@pytest.mark.parametrize("payload", [None, [], "match", {"decisions": "no"}, {}])
def test_an_answer_that_makes_no_sense_decides_nothing(monkeypatch, payload):
    _answer(monkeypatch, payload)
    assert decide_many(ITEMS, "a note") == {}


def test_a_failed_call_decides_nothing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr("app.entity_resolution.batch.complete_json", boom)
    assert decide_many(ITEMS, "a note") == {}


def test_nothing_to_decide_makes_no_call():
    assert decide_many([], "a note") == {}


def test_a_long_note_is_split_rather_than_sent_whole(monkeypatch):
    """Past a certain length the model loses track of which shortlist belongs
    to which name. Two calls still beat twenty."""
    calls = []

    def count(*a, **k):
        calls.append(1)
        return {"decisions": []}

    monkeypatch.setattr("app.entity_resolution.batch.complete_json", count)
    many = [(f"Name {i}", "person", [_Candidate(f"c{i}", f"Candidate {i}")])
            for i in range(MAX_PER_CALL * 2 + 1)]
    decide_many(many, "a note")
    assert len(calls) == 3


def test_a_decision_without_a_confidence_is_not_trusted_as_high(monkeypatch):
    _answer(monkeypatch, {"decisions": [
        {"mentioned": "Rajesh", "decision": "match", "match_id": "r1"},
    ]})
    # Only a high-confidence match links; medium creates a flagged record.
    assert decide_many(ITEMS, "a note")["Rajesh"].confidence == "medium"
