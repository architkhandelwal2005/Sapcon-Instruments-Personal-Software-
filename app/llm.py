"""The single seam for every LLM call that isn't the primary extraction pass -
the entity-match decision, the verification pass, and query-time synthesis.

Same provider dispatch and privacy gate as extraction: EXTRACTION_PROVIDER
selects the model, and 'gemini' is the free tier that must never see real
meeting data. Flip it to 'anthropic' in .env before the first real recording.
"""

import json
import os
import time

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()

_RETRIES = 3  # transient TLS/connection resets to the model API are common here

_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


def normalize_ws(s: str) -> str:
    """Collapse every run of whitespace to a single space. Transcripts wrap
    words across newlines, so quote-grounding checks compare normalised forms
    on both sides."""
    import re

    return re.sub(r"\s+", " ", s or "").strip()


def is_grounded(quote: str, source: str) -> bool:
    """True when `quote` appears verbatim (whitespace-normalised) in `source` -
    the self-check that a model-returned 'quote' is a real span and not a
    paraphrase."""
    q = normalize_ws(quote)
    return bool(q) and q in normalize_ws(source)


def complete_json(system: str, user: str, *, max_tokens: int = 1024):
    """Call the configured model at temperature 0 and return the first JSON
    value ([...] or {...}) parsed out of its response. Retries a few times on
    transient connection errors before giving up."""
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return _first_json(_raw_completion(system, user, max_tokens))
        except (ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
        except Exception as exc:  # httpx/httpcore connect errors don't subclass the stdlib ones
            if type(exc).__name__ not in ("ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError"):
                raise
            last_exc = exc
        if attempt < _RETRIES - 1:
            time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _raw_completion(system: str, user: str, max_tokens: int) -> str:
    if PROVIDER == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=_ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
    elif PROVIDER == "gemini":
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=user,
            config={
                "system_instruction": system,
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
        text = resp.text
    else:
        raise ValueError(f"Unknown EXTRACTION_PROVIDER: {PROVIDER!r}")

    return text


def _first_json(text: str):
    opens = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not opens:
        raise ValueError(f"No JSON found in model response: {text[:200]!r}")
    start = min(opens)
    close = "]" if text[start] == "[" else "}"
    return json.loads(text[start : text.rindex(close) + 1])
