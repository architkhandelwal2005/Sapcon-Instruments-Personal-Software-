"""Turn meeting notes and CRM records into a grounded answer.

Two kinds of source, checked two different ways. A transcript claim is
testimony - the transcription and the extraction can both be wrong - so it must
carry a verbatim quote, which is checked against that transcript. A record is
the system's own state, so a "quote" of it would only prove we printed what we
printed; instead the reference must name a record actually in the pack, which is
a deterministic check and a stronger one.

A note too long for the budget is shown as its summary alone and labelled. Its
quotes are then checked against the summary, never the transcript the model
never saw - otherwise a made-up quote could coincidentally match the full text
and be marked as verified, which is the worst way for this to fail.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

from app.llm import complete_json, is_grounded
from app.query.budget import PackedNote
from app.query.facts import FactPack, render_fact_pack

SYNTHESIS_PROMPT = """You answer questions for a salesperson at Sapcon Instruments using ONLY the \
material provided. There are two kinds.

MEETING NOTES are what someone said after a visit or a call. Each has a number, a date, an \
optional summary, and usually the raw transcript.
RECORDS are rows from the CRM itself - contact details, tasks, leads, connections, decisions. \
Each has a reference like F3.

Rules:
- Use only what is provided. If it does not answer the question, say so plainly - do not guess or \
use outside knowledge.
- A claim taken from a meeting note must cite that note AND a short VERBATIM quote from its \
transcript (copy it exactly, do not paraphrase).
- A claim taken from a record must cite the record's reference and NO quote. Never invent a quote \
for a record.
- A note marked SUMMARY ONLY has no transcript here. You may use what its summary says, cite the \
note with no quote, and make clear the detail is unverified.
- A record marked [unreviewed] has not been checked by a human yet. You may use it, but say so.
- Be concise and direct. Prefer specifics - names, numbers, dates, who owns what.
- If sources disagree, or a fact is hedged in the transcript, say so.

Return JSON: {"answer": "<prose>", "citations": [{"note": <number>, "quote": "<verbatim span>"} \
or {"ref": "<record reference, e.g. F3>"}]}."""


@dataclass
class Citation:
    source: Literal["transcript", "record"]
    grounded: bool
    note_index: Optional[int] = None
    meeting_id: Optional[str] = None
    meeting_date: Optional[date] = None
    quote: Optional[str] = None
    fact_ref: Optional[str] = None
    fact_text: Optional[str] = None
    url_path: Optional[str] = None


@dataclass
class QueryAnswer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    notes_used: int = 0
    ungrounded_citations: int = 0
    notes_summary_only: int = 0
    notes_dropped: int = 0
    facts_used: int = 0


def _format_notes(packed: list[PackedNote]) -> str:
    blocks = []
    for i, p in enumerate(packed, start=1):
        n = p.note
        head = f"NOTE [{i}] - {n.meeting_date}"
        if n.primary_contact_name:
            head += f" - met {n.primary_contact_name}"
        if p.full:
            summary = f"\nSummary: {n.summary}" if n.summary else ""
            blocks.append(f"{head}{summary}\nTranscript:\n{n.transcript}")
        else:
            blocks.append(f"{head} - SUMMARY ONLY, do not quote\nSummary: {n.summary}")
    return "\n\n---\n\n".join(blocks)


def answer_from_notes(
    question: str,
    packed: list[PackedNote],
    *,
    facts: Optional[FactPack] = None,
    notes_dropped: int = 0,
) -> QueryAnswer:
    facts = facts or FactPack()
    if not packed and not facts.facts:
        return QueryAnswer(text="Nothing in the CRM touches that yet.", notes_used=0)

    parts = [f"QUESTION: {question}"]
    if packed:
        parts.append(f"MEETING NOTES:\n\n{_format_notes(packed)}")
    if facts.facts:
        parts.append(f"RECORDS:\n{render_fact_pack(facts)}")
    raw = complete_json(SYNTHESIS_PROMPT, "\n\n".join(parts), max_tokens=2048)

    summary_only = sum(1 for p in packed if not p.full)
    if not isinstance(raw, dict):
        return QueryAnswer(text="(could not parse a structured answer)", notes_used=len(packed),
                           notes_summary_only=summary_only, notes_dropped=notes_dropped,
                           facts_used=len(facts.facts))

    citations, ungrounded = _citations(raw.get("citations", []), packed, facts)
    return QueryAnswer(
        text=(raw.get("answer") or "").strip() or "(no answer returned)",
        citations=citations,
        notes_used=len(packed),
        ungrounded_citations=ungrounded,
        notes_summary_only=summary_only,
        notes_dropped=notes_dropped,
        facts_used=len(facts.facts),
    )


def _citations(raw_citations, packed: list[PackedNote], facts: FactPack) -> tuple[list[Citation], int]:
    by_ref = facts.by_ref()
    out: list[Citation] = []
    ungrounded = 0

    for c in raw_citations or []:
        if not isinstance(c, dict):
            continue

        ref = (c.get("ref") or "").strip()
        if ref:
            fact = by_ref.get(ref)
            if fact is None:
                # A reference to a record that was never shown is a fabrication,
                # and unlike a quote there is nothing to show the reader.
                ungrounded += 1
                out.append(Citation(source="record", grounded=False, fact_ref=ref))
            else:
                out.append(Citation(source="record", grounded=True, fact_ref=ref,
                                    fact_text=fact.text, url_path=fact.url_path))
            continue

        idx = c.get("note")
        quote = (c.get("quote") or "").strip()
        if not isinstance(idx, int) or not (1 <= idx <= len(packed)):
            continue
        p = packed[idx - 1]
        # Ground against what the model was actually shown.
        against = p.note.transcript if p.full else (p.note.summary or "")
        grounded = bool(quote) and is_grounded(quote, against)
        if not grounded:
            ungrounded += 1
        out.append(Citation(source="transcript", grounded=grounded, note_index=idx,
                            meeting_id=p.note.meeting_id, meeting_date=p.note.meeting_date,
                            quote=quote or None))
    return out, ungrounded
