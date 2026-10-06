# -*- coding: utf-8 -*-
"""Keeping the fact that a note named a record.

A meeting could be reached from a company three ways: it was the primary
contact, a relation referenced it, or a task was tied to it. A field visit
produces all three; an internal meeting produces none, because it has no
outside primary contact, its connections are between people, and its tasks are
about work rather than accounts.

So "Indofil has a new project at Dahej" resolved Indofil, matched the right
record, enriched it - and dropped the association. Asking about Indofil
returned an empty contact card. Most of what a sales head records from the
office is internal meetings.
"""

from dataclasses import dataclass
from typing import Optional

from app.ingestion.pipeline import _write_mentions
from app.query.retrieve import _TOUCHES
from scripts.backfill_mentions import _names, _only_inside_a_longer_name, _spans


@dataclass
class _Resolved:
    entity_id: Optional[str]


class _Cursor:
    def __init__(self, existing):
        self.existing = existing
        self.inserted = []
        self.selected = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.selected += 1

    def fetchall(self):
        return [(e,) for e in self.existing]

    def executemany(self, sql, rows):
        self.inserted.extend(rows)


class _Conn:
    def __init__(self, existing=()):
        self.cur = _Cursor(list(existing))

    def cursor(self):
        return self.cur


def _write(resolved, existing=()):
    conn = _Conn(existing)
    _write_mentions(conn, "m1", resolved)
    return conn.cur.inserted


class TestWhatGetsRecorded:
    def test_one_row_per_entity_the_note_named(self):
        got = _write({"Indofil": _Resolved("e1"), "Salvi Chemicals": _Resolved("e2")})
        assert got == [("m1", "e1"), ("m1", "e2")]

    def test_the_same_record_named_twice_is_recorded_once(self):
        """Two spellings of one company resolve to the same record."""
        got = _write({"Indofil": _Resolved("e1"), "Indofil Industries": _Resolved("e1")})
        assert got == [("m1", "e1")]

    def test_a_correction_adds_only_what_is_new(self):
        """A correction appends to an existing meeting and runs this again."""
        got = _write({"Indofil": _Resolved("e1"), "Praj": _Resolved("e2")}, existing=["e1"])
        assert got == [("m1", "e2")]

    def test_nothing_new_writes_nothing(self):
        assert _write({"Indofil": _Resolved("e1")}, existing=["e1"]) == []

    def test_a_meeting_that_named_nobody_writes_nothing(self):
        assert _write({}) == []

    def test_an_entity_without_an_id_is_skipped(self):
        assert _write({"Indofil": _Resolved("e1"), "?": _Resolved(None)}) == [("m1", "e1")]


class TestRetrievalCanFollowIt:
    def test_being_named_is_a_way_to_reach_a_meeting(self):
        assert "meeting_mentions" in _TOUCHES

    def test_the_older_paths_are_still_there(self):
        """A mention is an addition, not a replacement - a field visit should
        still be reachable by its primary contact and its relations."""
        assert "primary_contact_id" in _TOUCHES
        assert "from relations" in _TOUCHES
        assert "from tasks" in _TOUCHES


class TestTheBackfillRefusesToGuess:
    """The backfill matches stored transcripts instead of re-running
    resolution, so it has no readback and nobody checking it. It is
    deliberately blunter than the live path.
    """

    def test_a_bare_first_name_is_not_evidence_for_a_person(self):
        """The book holds a customer called Raghav; so does his own office.
        Dropping a real match is the safe direction here - the live path
        records Raghav correctly from the resolver's own answer."""
        assert _names("Raghav", [], "person") == []

    def test_a_full_name_is(self):
        assert _names("Sawant Patel", [], "person") == ["Sawant Patel"]

    def test_a_company_keeps_its_single_word_name(self):
        assert _names("Indofil", [], "company") == ["Indofil"]

    def test_a_roster_name_is_kept(self):
        """A single-word roster name said in an internal meeting is that
        colleague - the roster is thirty people, not seventeen hundred."""
        assert _names("Sanjeevani", [], "employee") == ["Sanjeevani"]

    def test_aliases_count(self):
        assert "Thermax" in _names("Thermax Limited", ["Thermax"], "company")

    def test_a_name_too_short_to_be_distinctive_is_dropped(self):
        assert _names("ACC", [], "company") == []

    def test_a_name_inside_a_longer_word_does_not_match(self):
        """"Praj" must not match inside "Prajapati"."""
        assert _spans("Nilesh Prajapati attended", "Praj") == []
        assert _spans("complaints from Praj and Thermax", "Praj")

    def test_a_name_ending_in_punctuation_still_matches(self):
        assert _spans("we met L&T Ltd. yesterday", "L&T Ltd.")

    def test_matching_ignores_case(self):
        assert _spans("INDOFIL has a new project", "Indofil")

    def test_a_record_that_only_appeared_inside_a_longer_name_is_dropped(self):
        """"Pooja" matched only because "Pooja Pandit" was said."""
        text = "Pooja Pandit will handle it"
        short, long = _spans(text, "Pooja"), _spans(text, "Pooja Pandit")
        assert _only_inside_a_longer_name(short, short + long)

    def test_a_record_named_in_its_own_right_is_kept(self):
        text = "Pooja Pandit will handle it, and Pooja separately"
        short, long = _spans(text, "Pooja"), _spans(text, "Pooja Pandit")
        assert not _only_inside_a_longer_name(short, short + long)

    def test_the_longer_name_itself_is_always_kept(self):
        text = "Pooja Pandit will handle it"
        short, long = _spans(text, "Pooja"), _spans(text, "Pooja Pandit")
        assert not _only_inside_a_longer_name(long, short + long)
