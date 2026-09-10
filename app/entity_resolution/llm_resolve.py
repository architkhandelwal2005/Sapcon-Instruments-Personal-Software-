"""The entity-match decision: given a name mentioned in a note plus a
shortlist of existing entities that might be the same, an LLM decides
match / new / uncertain with full context. Never merges on 'uncertain' -
that's an unrecoverable mistake, so doubt always creates a new entity that's
flagged for a human instead.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from app.entity_resolution.matcher import Candidate
from app.llm import complete_json

PROMPT = """You decide whether a name mentioned in a sales meeting note refers to an entity that \
already exists in the CRM, or is someone/something new. You get: the mentioned name and its type, \
the surrounding sentence(s) from the note, and a shortlist of existing entities with their details. \
Reply with JSON: {"decision": "match" | "new" | "uncertain", "match_id": <id or null>, "reason": \
"<one line>", "confidence": "high" | "medium" | "low"}. \
Rules: only "match" if you are genuinely confident it's the same real-world entity (same person at \
the same kind of company, or the same company under a spelling variant). If two candidates are \
plausible, or you can't tell a common name apart, say "uncertain". Never guess a match to avoid \
saying "new"."""


@dataclass
class MatchDecision:
    decision: Literal["match", "new", "uncertain"]
    match_id: Optional[str]
    reason: str
    confidence: Literal["high", "medium", "low"]


def decide_match(name: str, entity_type: str, context: str, candidates: list[Candidate]) -> MatchDecision:
    if not candidates:
        return MatchDecision("new", None, "no similar existing entity", "high")

    cand_lines = "\n".join(
        f'  id={c.id} | "{c.canonical_name}" ({c.entity_type})'
        + (f' | title: {c.title}' if c.title else "")
        + (f' | region: {c.region}' if c.region else "")
        + (f' | aliases: {", ".join(c.aliases)}' if c.aliases else "")
        for c in candidates
    )
    payload = (
        f'MENTIONED: "{name}" ({entity_type})\n'
        f"CONTEXT FROM THE NOTE:\n{context}\n\n"
        f"EXISTING CANDIDATES:\n{cand_lines}"
    )
    raw = complete_json(PROMPT, payload, max_tokens=512)
    decision = raw.get("decision", "uncertain")
    match_id = raw.get("match_id")
    if decision == "match" and match_id not in {c.id for c in candidates}:
        # model named an id that isn't in the shortlist - treat as uncertain
        decision, match_id = "uncertain", None
    return MatchDecision(
        decision=decision if decision in ("match", "new", "uncertain") else "uncertain",
        match_id=str(match_id) if match_id else None,
        reason=raw.get("reason", ""),
        confidence=raw.get("confidence", "low") if raw.get("confidence") in ("high", "medium", "low") else "low",
    )
