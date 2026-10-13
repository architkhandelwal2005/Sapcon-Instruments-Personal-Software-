"""Who changed what, in words a person reads, and an undo that cannot clobber.

The database half - change, record, undo, and the refusal when a field has
moved on since - was proved against the real database with throwaway records.
These pin the parts that decide behaviour without one.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.history import UNDO_WORDS, _plain, _same, ago, describe
from app.web.routes.history import _safe_back, with_undo


class TestHistoryReadsLikeEnglish:
    def test_a_task_marked_done(self):
        assert describe("task", "status", "open", "done") == "marked done"

    def test_a_task_reopened(self):
        assert describe("task", "status", "done", "open") == "reopened"

    def test_handing_a_task_over(self):
        after = [{"employee_id": "e1", "name": "Vishal Dixit"}]
        assert describe("task", "owners", [], after) == "gave it to Vishal Dixit"

    def test_taking_the_owner_off(self):
        assert describe("task", "owners", [{"employee_id": "e1", "name": "V"}], []) == "took the owner off"

    def test_a_field_set_for_the_first_time(self):
        assert describe("contact", "phone", None, "98260 80207") == "set phone to 98260 80207"

    def test_a_field_changed(self):
        assert describe("lead", "status", "open", "dropped") == "changed status from open to dropped"

    def test_a_date_reads_as_a_date(self):
        assert describe("lead", "next_follow_up_due", None, "2026-11-05") == "set follow-up date to 05 Nov"

    def test_notes_are_not_dumped_into_the_line(self):
        """A paragraph of notes would swamp the history list."""
        assert describe("lead", "notes", "old", "a" * 500) == "edited the notes"

    def test_a_long_value_is_shortened(self):
        line = describe("contact", "title", None, "x" * 100)
        assert len(line) < 70


class TestWhatCountsAsAChange:
    def test_whitespace_alone_is_not_a_change(self):
        assert _plain("  Vishal  ") == "Vishal"

    def test_an_emptied_box_clears_the_field(self):
        assert _plain("   ") is None

    def test_dates_are_stored_as_text(self):
        """So a value read back from jsonb compares equal to the one written."""
        assert _plain(date(2026, 11, 5)) == "2026-11-05"

    def test_the_same_owner_under_a_different_spelling(self):
        """"Vishal" heard on a call and "Vishal Dixit" picked from a list are one
        person. Recording a change between them would be noise."""
        a = [{"employee_id": "e1", "name": "Vishal"}]
        b = [{"employee_id": "e1", "name": "Vishal Dixit"}]
        assert _same(a, b)

    def test_a_different_owner_is_a_change(self):
        assert not _same([{"employee_id": "e1", "name": "V"}], [{"employee_id": "e2", "name": "V"}])

    def test_unmatched_owners_compare_by_name(self):
        a = [{"employee_id": None, "name": "Shivani"}]
        assert _same(a, [{"employee_id": None, "name": " shivani "}])

    def test_owner_order_does_not_matter(self):
        x, y = {"employee_id": "e1", "name": "A"}, {"employee_id": "e2", "name": "B"}
        assert _same([x, y], [y, x])


class TestUndoWording:
    def test_every_outcome_has_words(self):
        """The undo bar and the WhatsApp reply both read this table, so a
        missing key would show one of them a blank."""
        for code in ("done", "changed", "notyours", "already", "missing"):
            assert UNDO_WORDS[code]

    def test_the_refusal_says_why(self):
        assert "changed again" in UNDO_WORDS["changed"]


class TestRedirectsStayOnThisSite:
    @pytest.mark.parametrize("back", ["https://evil.example", "//evil.example", "javascript:x", ""])
    def test_anything_but_a_local_path_goes_home(self, back):
        """Undo posts a `back` address. A full URL would let a crafted form send
        someone to another site the moment they clicked."""
        assert _safe_back(back) == "/"

    def test_a_local_path_is_kept(self):
        assert _safe_back("/leads/abc") == "/leads/abc"

    def test_an_old_query_string_is_dropped(self):
        """Otherwise "?undo=12" from the last edit would still be showing."""
        assert _safe_back("/leads/abc?undo=12") == "/leads/abc"

    def test_an_edit_that_changed_something_offers_undo(self):
        assert with_undo("/tasks", 5, 6).headers["location"] == "/tasks?undo=5,6"

    def test_an_edit_that_changed_nothing_offers_no_undo(self):
        assert with_undo("/tasks", None, None).headers["location"] == "/tasks"


class TestAgo:
    def _at(self, **delta):
        return datetime.now(timezone.utc) - timedelta(**delta)

    def test_just_now(self):
        assert ago(self._at(seconds=10)) == "just now"

    def test_minutes(self):
        assert ago(self._at(minutes=5)) == "5 min ago"

    def test_hours(self):
        assert ago(self._at(hours=3)) == "3 h ago"

    def test_older_shows_the_date(self):
        assert ago(datetime(2026, 10, 1, tzinfo=timezone.utc)) == "01 Oct"
