"""The readback is the only place the owner can catch a wrong entity link from
his phone, so these tests pin the things that must survive every trim: the
marked lines, and the link."""

from datetime import date

import pytest

from app.entity_resolution.resolve import ResolutionResult
from app.minutes.generate import DecisionRow, MeetingMinutesData, TaskRow
from app.whatsapp.readback import HARD_LIMIT, meeting_readback_reply

URL = "https://sapcon.example.com/meetings/47f20556-df51-41a6-9acf-2e841177a75e"


def linked(heard, canonical, entity_type="person"):
    return ResolutionResult(entity_id="e", outcome="linked", canonical_name=canonical,
                            review_status="auto_confirmed", mentioned_name=heard,
                            entity_type=entity_type)


def created(name):
    return ResolutionResult(entity_id="e", outcome="created", canonical_name=name,
                            review_status="pending", mentioned_name=name, entity_type="person")


def uncertain(name, dup):
    return ResolutionResult(entity_id="e", outcome="uncertain_created", canonical_name=name,
                            review_status="pending", mentioned_name=name,
                            possible_duplicate_of=dup, entity_type="company")


def task(description, owners=(), due=None):
    return TaskRow(description=description, related_entity_name=None, related_entity_id=None,
                   due_date=due, status="open", confidence="high", review_status="pending",
                   source_quote=None, task_id="t",
                   assignees=[{"name": o, "employee_id": None} for o in owners])


def minutes(*, summary="Visited Parag Foods.", tasks=(), decisions=(), kind="field_visit",
            contact="Parag Foods"):
    return MeetingMinutesData(
        meeting_id="m", meeting_date=date(2026, 9, 26), location=None, audio_url=None,
        raw_transcript="...", summary=summary, review_status="pending",
        primary_contact_name=contact, primary_contact_id=None, connections=[],
        tasks=list(tasks), kind=kind, attendees=[],
        decisions=[DecisionRow(description=d, confidence="high", review_status="pending",
                               source_quote=None, decision_id="d") for d in decisions],
    )


def test_link_to_a_different_name_is_flagged_and_shows_both_names():
    out = meeting_readback_reply(minutes(), [linked("Rajesh", "Rajesh Gupta")], URL)
    assert '! "Rajesh" -> linked to Rajesh Gupta' in out


def test_our_own_staff_are_routine_not_flagged():
    out = meeting_readback_reply(minutes(), [linked("Vishal", "Vishal Dixit", "employee")], URL)
    assert "(our team)" in out
    assert "! " not in out


def test_possible_duplicate_is_flagged_with_the_record_it_might_be():
    out = meeting_readback_reply(minutes(), [uncertain("Parag", "Parag Milk Foods Pvt Ltd")], URL)
    assert "! " in out and "may be the same as Parag Milk Foods Pvt Ltd" in out


def test_a_plainly_new_name_is_routine():
    out = meeting_readback_reply(minutes(), [created("Mukesh Shah")], URL)
    assert "Mukesh Shah -> new" in out
    assert "! " not in out


def test_task_shows_owner_and_due_date_and_says_when_there_is_none():
    out = meeting_readback_reply(
        minutes(tasks=[task("Send the quote", ["Vishal Dixit"], date(2026, 10, 3)),
                       task("Chase the tender")]),
        [], URL)
    assert "[ ] Send the quote -- Vishal Dixit -- 03 Oct" in out
    assert "[ ] Chase the tender -- no owner -- no due date" in out


def test_url_is_always_the_last_line():
    out = meeting_readback_reply(minutes(), [created("A")], URL)
    assert out.splitlines()[-1] == URL


def test_reply_wording_promises_adding_only_because_corrections_are_additive():
    # append_correction cannot unlink or delete; the copy must not imply it can.
    out = meeting_readback_reply(minutes(), [], URL)
    assert "ADD" in out
    assert "fix" not in out.lower()


def _pathological():
    return (
        minutes(summary="A very long recap. " * 200,
                tasks=[task(f"Task number {i} with a fairly wordy description", ["Someone"],
                            date(2026, 10, 1)) for i in range(15)],
                decisions=[f"Decision number {i} recorded at length" for i in range(10)]),
        [linked(f"Heard{i}", f"Record Number {i}") for i in range(12)]
        + [created(f"New Person Number {i}") for i in range(8)],
    )


def test_a_huge_meeting_still_fits_whatsapp():
    data, resolutions = _pathological()
    out = meeting_readback_reply(data, resolutions, URL)
    assert len(out) <= HARD_LIMIT
    assert out.splitlines()[-1] == URL


def test_trimming_never_silently_drops_a_flagged_name():
    data, resolutions = _pathological()
    out = meeting_readback_reply(data, resolutions, URL)
    flagged = sum(1 for r in resolutions if r.outcome != "created" and r.entity_type != "employee")
    shown = sum(1 for line in out.splitlines() if line.startswith("! "))
    assert shown == flagged or f"{flagged} name(s) need checking" in out


def test_short_meeting_is_not_trimmed_at_all():
    out = meeting_readback_reply(
        minutes(summary="Short recap.", tasks=[task("One task", ["Vishal"], date(2026, 10, 1))],
                decisions=["Quote at list minus 8%"]),
        [linked("Rajesh", "Rajesh Gupta")], URL)
    assert "Short recap." in out
    assert "Quote at list minus 8%" in out
    assert "more recorded" not in out and "more tasks" not in out


def test_internal_meeting_says_so():
    out = meeting_readback_reply(minutes(kind="internal", contact=None), [], URL)
    assert out.startswith("Internal meeting 26 Sep")


@pytest.mark.parametrize("summary", ["", None])
def test_missing_summary_does_not_produce_an_empty_heading(summary):
    out = meeting_readback_reply(minutes(summary=summary), [created("A")], URL)
    assert "WHAT I HEARD" not in out
