"""Second pass: check every extracted item against the transcript and attach
the verbatim sentence that supports it. Anything the verifier can't ground in
the transcript is forced to low confidence so it lands in the review queue
instead of being trusted.

Runs on the same provider as extraction (respects the privacy gate - real
data must not touch the free Gemini tier), but it's a fresh call with an
adversarial prompt, so it's an independent check even when the model is the
same. Cross-model verification is a later hardening knob.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from app.extraction.schema import ExtractionResult


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()

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
    for i, t in enumerate(result.tasks):
        claims.append((f"task:{i}", t.description))
    return claims


def _call(transcript: str, claims: list[str]) -> list[ClaimCheck]:
    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(claims))
    user = f"TRANSCRIPT:\n{transcript}\n\nCLAIMS:\n{numbered}"

    if PROVIDER == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=4096,
            temperature=0,
            system=VERIFY_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        raw = json.loads(text[text.index("[") : text.rindex("]") + 1])
    else:
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            contents=user,
            config={"system_instruction": VERIFY_PROMPT, "response_mime_type": "application/json", "temperature": 0},
        )
        raw = json.loads(resp.text)

    norm_transcript = _norm(transcript)
    by_index = {item["index"]: item for item in raw}
    out = []
    for i in range(len(claims)):
        item = by_index.get(i, {})
        quote = item.get("quote") or None
        # Self-check: a "quote" the verifier paraphrased or invented is not
        # actually in the transcript. Only a real verbatim span counts.
        grounded = bool(quote) and _norm(quote) in norm_transcript
        out.append(ClaimCheck(quote=(_norm(quote) if grounded else None), supported=bool(item.get("supported")) and grounded))
    return out


def verify(transcript: str, result: ExtractionResult) -> ExtractionResult:
    """Attach source_quotes, drop unsupported entity attributes, and force
    unsupported connections/tasks/entities to low confidence."""
    claims = _build_claims(result)
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
        elif kind == "task":
            result.tasks[idx].source_quote = check.quote
            if not check.supported:
                result.tasks[idx].confidence = "low"

    return result
