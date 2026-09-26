"""How much of the material fits in one question.

Retrieval hands back every meeting that touches the entity, and the whole
transcript of each went into the prompt with nothing bounding it. A
well-connected customer with thirty meetings therefore sent thirty full
transcripts in a single call - slow, expensive against a 500-a-day quota, and
eventually past the context window, at which point the answer fails rather than
degrades.

Newest first, because a question about a customer is nearly always about where
things stand now. A note that does not fit whole is kept as its summary, which
the pipeline already wrote; past that, notes are dropped and counted, so the
answer can say it was working from part of the picture.
"""

from dataclasses import dataclass

from app.query.retrieve import MeetingNote

MAX_CONTEXT_CHARS = 60_000
FACT_SHARE = 0.40       # records may take up to this much; the rest goes to transcripts
MAX_NOTES = 40


@dataclass
class PackedNote:
    note: MeetingNote
    full: bool          # False: the model sees the summary only and must not quote it


def pack_notes(
    notes: list[MeetingNote],
    *,
    budget: int,
    max_notes: int = MAX_NOTES,
) -> tuple[list[PackedNote], int]:
    """(packed, dropped). Newest first; full transcripts while the budget
    lasts, then summaries, then nothing."""
    ordered = sorted(notes, key=lambda n: n.meeting_date, reverse=True)
    kept, dropped = ordered[:max_notes], len(ordered[max_notes:])

    packed: list[PackedNote] = []
    used = 0
    for note in kept:
        full_cost = len(note.transcript or "") + 120
        summary_cost = len(note.summary or "") + 120
        if used + full_cost <= budget:
            used += full_cost
            packed.append(PackedNote(note=note, full=True))
        elif used + summary_cost <= budget and (note.summary or "").strip():
            used += summary_cost
            packed.append(PackedNote(note=note, full=False))
        else:
            dropped += 1
    return packed, dropped
