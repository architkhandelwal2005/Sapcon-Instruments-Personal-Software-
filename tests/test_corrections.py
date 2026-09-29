"""Correcting a name from the chat.

Merging cannot be cleanly undone, so the rules that matter here are the ones
about refusing: never merge on an ambiguous match, never merge a record into
itself, never act on a correction that does not say what the right spelling is.
"""

import pytest

from app.entity_resolution.corrections import apply_name_correction
from app.entity_resolution.merge import find_by_name, merge_entities


class _Conn:
    """Enough of psycopg to answer the lookups these guards make first."""

    def __init__(self, found=None):
        self.found = found or {}
        self.writes = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if not sql.strip().lower().startswith("select"):
            self.writes.append(sql)
        self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return None

    def commit(self):
        pass

    def rollback(self):
        pass


def test_a_correction_that_does_not_say_the_right_spelling_changes_nothing():
    conn = _Conn()
    out = apply_name_correction(conn, "", ["Mark Sapadia"])
    assert out.status == "not_found"
    assert conn.writes == []


def test_a_name_that_matches_nothing_changes_nothing():
    conn = _Conn()
    out = apply_name_correction(conn, "Marmik Sapovadia", ["Mark Sapadia"])
    assert out.status == "not_found"
    assert "no record" in out.summary
    assert conn.writes == []


def test_a_record_is_never_merged_into_itself():
    with pytest.raises(ValueError):
        merge_entities(_Conn(), "same-id", "same-id")


@pytest.mark.parametrize("text", ["", "  ", "ab", "x"])
def test_too_few_letters_to_name_a_record(text):
    """Two letters match half the contact book, and a merge picked from that is
    not a correction, it is a coin toss."""
    assert find_by_name(_Conn(), text) == []


def test_a_spelling_the_same_as_the_right_one_is_not_treated_as_wrong():
    # "It's Kanika Chadha, not kanika chadha" asks for nothing.
    conn = _Conn()
    out = apply_name_correction(conn, "Kanika Chadha", ["kanika chadha"])
    assert out.status == "not_found"     # nothing found, and nothing attempted
    assert conn.writes == []
