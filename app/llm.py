"""The single seam for every LLM call that isn't the primary extraction pass -
the entity-match decision, the verification pass, and query-time synthesis.

Same provider dispatch and privacy gate as extraction: EXTRACTION_PROVIDER
selects the model, and 'gemini' is the free tier that must never see real
meeting data. Flip it to 'anthropic' in .env before the first real recording.
"""

import json
import os
import re
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
    return _with_retries(lambda: _first_json(_raw_completion(system, user, max_tokens)))


def complete_json_with_image(system: str, user: str, image_bytes: bytes, mime_type: str, *, max_tokens: int = 2048):
    """Same as complete_json but the user turn also carries an image - card sheets
    and diary pages. Same provider gate: real photographed customer data is exactly
    as sensitive as a real transcript and must not touch the free Gemini tier
    either."""
    return _with_retries(
        lambda: _first_json(_raw_completion(system, user, max_tokens, image_bytes=image_bytes, mime_type=mime_type))
    )


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """Transcribe a voice note to text via Gemini's native audio understanding.

    Always Gemini, regardless of EXTRACTION_PROVIDER - Anthropic's API has no
    audio input, so there is no 'anthropic' path here the way there is for
    complete_json/complete_json_with_image. A real voice note is exactly as
    sensitive as a real transcript; if EXTRACTION_PROVIDER is later set to
    'anthropic' for that reason, transcription itself still touches Gemini
    until this function is pointed at a paid Gemini key or another audio-
    capable provider."""
    return _with_retries(lambda: _raw_transcribe(audio_bytes, mime_type))


def _raw_transcribe(audio_bytes: bytes, mime_type: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            "Transcribe this audio verbatim, in whatever language(s) are spoken. "
            "Return only the transcript text - no commentary, no timestamps, no speaker labels.",
        ],
        config={"temperature": 0},
    )
    return (resp.text or "").strip()


# A rate-limited call says how long to wait. The per-minute quota asks for a
# few seconds and is worth sitting out; the per-day quota asks for a similar
# number but keeps refusing all day, so a cap stops us waiting inside a webhook
# for a call that will not succeed. Above the cap the caller gets the error and
# records the note for a later retry instead.
_RATE_LIMIT_WAIT_CAP = 30


def _retry_after(exc: Exception) -> float | None:
    """Seconds the API asked us to wait, when the error is a rate limit worth
    waiting out - otherwise None."""
    text = str(exc)
    if "RESOURCE_EXHAUSTED" not in text and "429" not in text and "rate_limit" not in text:
        return None
    match = re.search(r"['\"]retryDelay['\"]:\s*['\"](\d+(?:\.\d+)?)s", text) or re.search(
        r"retry in (\d+(?:\.\d+)?)\s*s", text
    )
    wait = float(match.group(1)) + 1 if match else 5.0
    return wait if wait <= _RATE_LIMIT_WAIT_CAP else None


def with_retries(call):
    """Retry transient model-API failures: connection resets, and rate limits
    short enough to wait out. Shared by every model call - the extraction pass
    included, since that is the one a lost voice note dies on."""
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return call()
        except (ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            delay = 1.5 * (attempt + 1)
        except Exception as exc:  # httpx/httpcore connect errors don't subclass the stdlib ones
            asked = _retry_after(exc)
            if asked is None and type(exc).__name__ not in (
                "ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError"
            ):
                raise
            last_exc = exc
            delay = asked if asked is not None else 1.5 * (attempt + 1)
        if attempt < _RETRIES - 1:
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


_with_retries = with_retries  # the name the calls in this module already use


def _raw_completion(system: str, user: str, max_tokens: int, *, image_bytes: bytes | None = None, mime_type: str | None = None) -> str:
    if PROVIDER == "anthropic":
        import base64

        import anthropic

        content: list = []
        if image_bytes is not None:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": base64.b64encode(image_bytes).decode()},
            })
        content.append({"type": "text", "text": user})

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=_ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
    elif PROVIDER == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), user] if image_bytes is not None else user
        resp = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=contents,
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
