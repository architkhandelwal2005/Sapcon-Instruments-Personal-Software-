"""Turn a set of meeting notes into a grounded answer. The model writes prose
and cites each factual claim with a note number and a verbatim quote; we then
check every quote really appears in that note's transcript. An ungrounded
citation is kept but flagged, never silently shown as if it were solid.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.llm import complete_json, is_grounded
from app.query.retrieve import MeetingNote

SYNTHESIS_PROMPT = """You answer questions for a salesperson at Sapcon Instruments using ONLY the \
meeting notes provided. Each note has a number, a date, an optional summary, and the raw \
transcript. \

Rules:
- Use only what the notes say. If the notes don't answer the question, say so plainly - do not \
guess or use outside knowledge.
- Every factual claim in your answer must carry a citation to the note it came from and a short \
VERBATIM quote from that note's transcript (copy it exactly, do not paraphrase).
- Be concise and direct. Prefer specifics (names, dates, commitments) over generalities.
- If notes disagree or a fact is hedged/unconfirmed in the transcript, say so.

Return JSON: {"answer": "<prose, may reference notes as [1], [2] ...>", "citations": \
[{"note": <number>, "quote": "<verbatim span from that note>"}]}."""


@dataclass
class Citation:
    note_index: int
    meeting_id: str
    meeting_date: date
    quote: str
    grounded: bool


@dataclass
class QueryAnswer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    notes_used: int = 0
    ungrounded_citations: int = 0


def _format_notes(notes: list[MeetingNote]) -> str:
    blocks = []
    for i, n in enumerate(notes, start=1):
        head = f"NOTE [{i}] - {n.meeting_date}"
        if n.primary_contact_name:
            head += f" - met {n.primary_contact_name}"
        summary = f"\nSummary: {n.summary}" if n.summary else ""
        blocks.append(f"{head}{summary}\nTranscript:\n{n.transcript}")
    return "\n\n---\n\n".join(blocks)


def answer_from_notes(question: str, notes: list[MeetingNote]) -> QueryAnswer:
    if not notes:
        return QueryAnswer(text="No meeting notes touch that yet.", notes_used=0)

    user = f"QUESTION: {question}\n\nMEETING NOTES:\n\n{_format_notes(notes)}"
    raw = complete_json(SYNTHESIS_PROMPT, user, max_tokens=2048)
    if not isinstance(raw, dict):
        return QueryAnswer(text="(could not parse a structured answer)", notes_used=len(notes))

    citations: list[Citation] = []
    ungrounded = 0
    for c in raw.get("citations", []):
        idx = c.get("note")
        quote = (c.get("quote") or "").strip()
        if not isinstance(idx, int) or not (1 <= idx <= len(notes)) or not quote:
            continue
        note = notes[idx - 1]
        grounded = is_grounded(quote, note.transcript)
        if not grounded:
            ungrounded += 1
        citations.append(
            Citation(
                note_index=idx,
                meeting_id=note.meeting_id,
                meeting_date=note.meeting_date,
                quote=quote,
                grounded=grounded,
            )
        )

    return QueryAnswer(
        text=(raw.get("answer") or "").strip() or "(no answer returned)",
        citations=citations,
        notes_used=len(notes),
        ungrounded_citations=ungrounded,
    )
