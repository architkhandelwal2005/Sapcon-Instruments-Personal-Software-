"""The budget decides what the model is allowed to see, and the citation check
decides what counts as supported. Both are pure, so they are pinned here."""

from datetime import date
from unittest.mock import patch

import pytest

from app.query.budget import PackedNote, pack_notes
from app.query.facts import Fact, FactPack, render_fact_pack
from app.query.retrieve import MeetingNote
from app.query.synthesize import answer_from_notes


def note(day: int, transcript_len: int = 100, summary: str = "a summary") -> MeetingNote:
    return MeetingNote(
        meeting_id=f"m{day}", meeting_date=date(2026, 9, day),
        primary_contact_name="Someone", summary=summary, transcript="x" * transcript_len,
    )


def test_everything_fits_when_the_budget_is_generous():
    packed, dropped = pack_notes([note(1), note(2), note(3)], budget=100_000)
    assert [p.full for p in packed] == [True, True, True]
    assert dropped == 0


def test_newest_notes_are_read_first():
    packed, _ = pack_notes([note(1), note(9), note(5)], budget=100_000)
    assert [p.note.meeting_date.day for p in packed] == [9, 5, 1]


def test_a_note_that_does_not_fit_whole_is_kept_as_its_summary():
    big = note(9, transcript_len=5_000)
    small = note(1, transcript_len=50)
    # 5120 for the big note whole, leaving room for the small note's summary
    # (129) but not its transcript (170).
    packed, dropped = pack_notes([big, small], budget=5_260)
    assert packed[0].full is True and packed[0].note.meeting_date.day == 9
    assert packed[1].full is False and packed[1].note.meeting_date.day == 1
    assert dropped == 0


def test_notes_that_cannot_even_fit_as_a_summary_are_dropped_and_counted():
    packed, dropped = pack_notes([note(d, transcript_len=2_000) for d in (1, 2, 3)], budget=2_200)
    assert len(packed) == 1
    assert dropped == 2


def test_a_note_with_no_summary_cannot_degrade_to_one():
    packed, dropped = pack_notes([note(9, transcript_len=9_000, summary="")], budget=500)
    assert packed == [] and dropped == 1


def test_no_notes_is_not_an_error():
    assert pack_notes([], budget=1_000) == ([], 0)


def test_rendered_records_keep_their_references_and_admit_what_was_left_out():
    pack = FactPack(
        facts=[Fact(ref="F1", kind="task", row_id="t1", text="Task: call back", url_path="/tasks"),
               Fact(ref="F2", kind="lead", row_id="l1", text="Lead: Acme", url_path="/leads/l1")],
        dropped={"lead": 4},
    )
    rendered = render_fact_pack(pack)
    assert "[F1] Task: call back" in rendered
    assert "[F2] Lead: Acme" in rendered
    assert "4 more lead(s)" in rendered
    assert pack.by_ref()["F2"].url_path == "/leads/l1"


def _answer_with(raw, packed, facts=None):
    with patch("app.query.synthesize.complete_json", return_value=raw):
        return answer_from_notes("q", packed, facts=facts)


def test_a_real_quote_from_a_full_transcript_is_grounded():
    n = MeetingNote("m1", date(2026, 9, 1), "X", "s", "He will send the tender next week.")
    answer = _answer_with(
        {"answer": "A tender is coming.", "citations": [{"note": 1, "quote": "send the tender"}]},
        [PackedNote(note=n, full=True)],
    )
    assert answer.citations[0].grounded is True
    assert answer.ungrounded_citations == 0


def test_a_paraphrase_is_kept_but_flagged():
    n = MeetingNote("m1", date(2026, 9, 1), "X", "s", "He will send the tender next week.")
    answer = _answer_with(
        {"answer": "A tender is coming.", "citations": [{"note": 1, "quote": "a tender is on its way"}]},
        [PackedNote(note=n, full=True)],
    )
    assert answer.citations[0].grounded is False
    assert answer.ungrounded_citations == 1


def test_a_quote_from_a_summary_only_note_is_checked_against_the_summary():
    # The model never saw this transcript, so a quote matching it would be a
    # coincidence dressed up as verification.
    n = MeetingNote("m1", date(2026, 9, 1), "X", "Tender expected.", "He will send the tender next week.")
    answer = _answer_with(
        {"answer": "...", "citations": [{"note": 1, "quote": "send the tender next week"}]},
        [PackedNote(note=n, full=False)],
    )
    assert answer.citations[0].grounded is False
    assert answer.notes_summary_only == 1


def test_a_record_reference_is_checked_against_the_pack_not_quoted():
    pack = FactPack(facts=[Fact(ref="F3", kind="lead", row_id="l1",
                                text="Lead: Acme -- status open", url_path="/leads/l1")])
    answer = _answer_with({"answer": "Acme is open.", "citations": [{"ref": "F3"}]}, [], facts=pack)
    c = answer.citations[0]
    assert c.source == "record" and c.grounded is True
    assert c.quote is None and c.fact_text == "Lead: Acme -- status open"
    assert answer.ungrounded_citations == 0


def test_a_reference_to_a_record_that_was_never_shown_is_unsupported():
    pack = FactPack(facts=[Fact(ref="F1", kind="task", row_id="t1", text="Task: x", url_path="/tasks")])
    answer = _answer_with({"answer": "...", "citations": [{"ref": "F99"}]}, [], facts=pack)
    assert answer.citations[0].grounded is False
    assert answer.ungrounded_citations == 1


def test_records_alone_can_answer_a_question_with_no_meetings():
    # "Give me Rajesh's number" must work even if he has never been met.
    pack = FactPack(facts=[Fact(ref="F1", kind="contact", row_id="e1",
                               text="Contact card: Rajesh, phone 98765", url_path="/entities/e1")])
    answer = _answer_with({"answer": "98765", "citations": [{"ref": "F1"}]}, [], facts=pack)
    assert answer.text == "98765"
    assert answer.facts_used == 1


def test_with_neither_notes_nor_records_it_says_so_without_calling_the_model():
    with patch("app.query.synthesize.complete_json", side_effect=AssertionError("must not be called")):
        answer = answer_from_notes("q", [], facts=FactPack())
    assert "Nothing in the CRM" in answer.text


@pytest.mark.parametrize("raw", ["not a dict", None, 42])
def test_a_malformed_model_reply_does_not_crash_the_answer(raw):
    n = MeetingNote("m1", date(2026, 9, 1), "X", "s", "t")
    answer = _answer_with(raw, [PackedNote(note=n, full=True)])
    assert "could not parse" in answer.text
