"""Decide every name in one note with one model call.

Resolution asked the model once per name. A note naming eight people spent
eight calls inside a few seconds, on top of transcription, extraction,
verification and the planner - which is how a single voice note ran a
per-minute quota out by itself and came back as "today's AI limit is used up".

One call for the whole note instead. Each name keeps its own shortlist and its
own answer; nothing is pooled except the request.

The safety rules do not move, because they are what make this affordable to get
wrong. A decision is only accepted for a name that was asked about, and only
when the id it names is on that name's own shortlist - a model that answers
about the wrong person, or invents an id, is treated as having said nothing.
Anything it does not answer for is resolved on its own afterwards, the way it
always was. The worst a bad batch can do is cost the calls it was meant to
save.
"""

from typing import Optional

from app.entity_resolution.llm_resolve import MatchDecision
from app.llm import complete_json

# Above this many names, the prompt is long enough that the model starts
# losing track of which shortlist belongs to which name. Split instead - two
# calls still beat eight.
MAX_PER_CALL = 8

_SYSTEM = """You decide, for each name mentioned in one sales meeting note, whether it refers
to an entity the CRM already holds or to someone new.

Each name has its own shortlist of existing candidates. Use only that name's shortlist for
that name.

Reply with JSON: {"decisions": [{"mentioned": "<the name exactly as given>",
"decision": "match" | "new" | "uncertain", "match_id": <id from THAT name's shortlist, or null>,
"reason": "<one line>", "confidence": "high" | "medium" | "low"}]}

Rules:
- Only "match" when you are genuinely confident it is the same real-world entity - the same
  person at the same kind of company, or the same company under a spelling variant.
- If two candidates are plausible, or you cannot tell a common name apart, say "uncertain".
  Uncertain is a safe answer here; a wrong match merges two customers' histories and cannot be
  cleanly undone.
- Never guess a match to avoid saying "new".
- A candidate marked [discussed recently] was talked about in the last few days. People say a
  bare first name for somebody already on their mind, so treat that as strong evidence when the
  mentioned name has no surname - and as no evidence at all when the names differ in any other
  way.
- Answer for every name you were given, using the name exactly as written."""


def decide_many(items: list, context: str, recently: Optional[set] = None) -> dict:
    """`items` is [(name, entity_type, candidates)].

    Returns {name: MatchDecision} for the names it answered about safely. A
    name missing from the result has not been decided and must be resolved on
    its own - never assumed."""
    if not items:
        return {}

    out = {}
    for start in range(0, len(items), MAX_PER_CALL):
        out.update(_one_call(items[start:start + MAX_PER_CALL], context, recently or set()))
    return out


def _one_call(items: list, context: str, recently: set) -> dict:
    recent = {r.lower() for r in recently}
    blocks = []
    for name, entity_type, candidates in items:
        lines = "\n".join(
            f'    id={c.id} | "{c.canonical_name}" ({c.entity_type})'
            + (f" | title: {c.title}" if c.title else "")
            + (f" | region: {c.region}" if c.region else "")
            + (f' | aliases: {", ".join(c.aliases)}' if c.aliases else "")
            + (" | [discussed recently]" if c.canonical_name.lower() in recent else "")
            for c in candidates
        )
        blocks.append(f'MENTIONED: "{name}" ({entity_type})\n  CANDIDATES:\n{lines}')

    payload = f"NOTE:\n{context}\n\n" + "\n\n".join(blocks)
    try:
        raw = complete_json(_SYSTEM, payload, max_tokens=1600)
    except Exception:
        return {}      # every name falls back to its own call
    if isinstance(raw, list):
        raw = {"decisions": raw}
    if not isinstance(raw, dict):
        return {}

    allowed = {name: {c.id for c in candidates} for name, _t, candidates in items}
    out = {}
    for answer in raw.get("decisions") or []:
        if not isinstance(answer, dict):
            continue
        name = str(answer.get("mentioned") or "").strip()
        if name not in allowed:
            continue        # answered about something nobody asked about
        decision = str(answer.get("decision") or "").strip().lower()
        if decision not in ("match", "new", "uncertain"):
            continue
        match_id = answer.get("match_id")
        if decision == "match" and match_id not in allowed[name]:
            # An id from another name's shortlist, or invented. Saying nothing
            # costs one call; accepting it could merge two customers.
            decision, match_id = "uncertain", None
        confidence = str(answer.get("confidence") or "medium").strip().lower()
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"
        out[name] = MatchDecision(
            decision=decision,                                  # type: ignore[arg-type]
            match_id=match_id if decision == "match" else None,
            reason=str(answer.get("reason") or "")[:300],
            confidence=confidence,                              # type: ignore[arg-type]
        )
    return out
