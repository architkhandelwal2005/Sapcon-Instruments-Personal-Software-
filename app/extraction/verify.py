"""Second pass: check every extracted item against the transcript and attach
the verbatim sentence that supports it. Anything the verifier can't ground in
the transcript is forced to low confidence so it lands in the review queue
instead of being trusted.

Runs on the same provider as extraction (respects the privacy gate - real
data must not touch the free Gemini tier), but it's a fresh call with an
adversarial prompt, so it's an independent check even when the model is the
same. Cross-model verification is a later hardening knob.
"""

from dataclasses import dataclass
from typing import Optional

from app.extraction.schema import ExtractionResult
from app.llm import complete_json, is_grounded, normalize_ws

VERIFY_PROMPT = """You are checking a structured extraction against the meeting transcript it \
came from. You will get the transcript and a numbered list of claims. For each claim, find the \
exact span of the transcript that supports it and return it verbatim (copy it character-for-\
character, do not paraphrase). If nothing in the transcript supports the claim, return null for \
the quote and supported=false. Be strict: a claim about a phone number or a title is only \
supported if that exact detail appears. Return a JSON array of {index, quote, supported}."""


@dataclass
class ClaimCheck:
    quote: Optional[str]
    supported: bool


def _build_claims(result: ExtractionResult) -> list[tuple[str, str]]:
    """(kind:pointer, claim text). pointer encodes what to update on failure."""
    claims: list[tuple[str, str]] = []
    for i, e in enumerate(result.entities):
        claims.append((f"entity:{i}", f'"{e.name}" is mentioned as a {e.entity_type}'))
        for attr in ("title", "phone", "email", "region"):
            val = getattr(e, attr)
            if val:
                claims.append((f"entity_attr:{i}:{attr}", f'"{e.name}" has {attr}: {val}'))
    for i, c in enumerate(result.connections):
        claims.append((f"connection:{i}", c.description))
    for i, d in enumerate(result.decisions):
        claims.append((f"decision:{i}", d.description))
    for i, t in enumerate(result.tasks):
        # The owners are part of the claim - a task pinned on the wrong person is
        # as wrong as a task that was never said.
        owners = f" (to be done by {', '.join(t.assignees)})" if t.assignees else ""
        claims.append((f"task:{i}", t.description + owners))
    return claims


def _call(transcript: str, claims: list[str]) -> list[ClaimCheck]:
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    user = f"TRANSCRIPT:\n{transcript}\n\nCLAIMS:\n{numbered}"
    raw = complete_json(VERIFY_PROMPT, user, max_tokens=4096)

    by_index = {item["index"]: item for item in raw}
    out = []
    for i in range(len(claims)):
        item = by_index.get(i, {})
        quote = item.get("quote") or None
        # Self-check: a "quote" the verifier paraphrased or invented is not
        # actually in the transcript. Only a real verbatim span counts.
        grounded = bool(quote) and is_grounded(quote, transcript)
        out.append(
            ClaimCheck(
                quote=(normalize_ws(quote) if grounded else None),
                supported=bool(item.get("supported")) and grounded,
            )
        )
    return out


def verify(transcript: str, result: ExtractionResult) -> ExtractionResult:
    """Attach source_quotes, drop unsupported entity attributes, and force
    unsupported connections/decisions/tasks/entities to low confidence."""
    claims = _build_claims(result)
    if not claims:
        return result
    checks = _call(transcript, [c[1] for c in claims])

    for (pointer, _), check in zip(claims, checks):
        kind, *rest = pointer.split(":")
        idx = int(rest[0])

        if kind == "entity":
            if not check.supported:
                result.entities[idx].confidence = "low"
        elif kind == "entity_attr":
            if not check.supported:
                setattr(result.entities[idx], rest[1], None)  # never store an ungrounded detail
        elif kind == "connection":
            result.connections[idx].source_quote = check.quote
            if not check.supported:
                result.connections[idx].confidence = "low"
        elif kind == "decision":
            result.decisions[idx].source_quote = check.quote
            if not check.supported:
                result.decisions[idx].confidence = "low"
        elif kind == "task":
            result.tasks[idx].source_quote = check.quote
            if not check.supported:
                result.tasks[idx].confidence = "low"

    return result
