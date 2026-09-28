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

from app.transcription.vocabulary import vocabulary_hint

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()

_RETRIES = 4  # connection resets and provider capacity spikes are both common here

_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# The free tier is served from spare capacity, and the small models run out of
# it first: on the evening this was written every -lite model answered 503 while
# gemini-3.5-flash answered normally. Retrying the same overloaded model harder
# does not help, so after the retries are spent the call is made once more
# against a bigger model. Slower and dearer per call, and better than losing a
# voice note. Set GEMINI_FALLBACK_MODEL to "" to turn it off.
_GEMINI_FALLBACK = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")


def gemini_models() -> list[str]:
    """The model to call, then what to fall back to when it is refusing."""
    if _GEMINI_FALLBACK and _GEMINI_FALLBACK != _GEMINI_MODEL:
        return [_GEMINI_MODEL, _GEMINI_FALLBACK]
    return [_GEMINI_MODEL]


def try_models(call):
    """call(model) -> result. Each model gets the full retry treatment before
    the next is tried, so a brief spike is ridden out on the model we wanted
    rather than escalating at the first refusal.

    A permanent error (a bad request, a bad key) is raised from the first model
    without trying the second - the second would fail the same way, and doubling
    a failure wastes a call from a daily allowance."""
    models = gemini_models()
    last_exc: Exception | None = None
    for model in models:
        try:
            return with_retries(lambda: call(model))
        except Exception as exc:
            if not _is_transient(exc):
                raise
            last_exc = exc
    raise last_exc  # type: ignore[misc]


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
    return try_models(lambda model: _first_json(_raw_completion(system, user, max_tokens, model=model)))


def complete_json_with_image(system: str, user: str, image_bytes: bytes, mime_type: str, *, max_tokens: int = 2048):
    """Same as complete_json but the user turn also carries an image - card sheets
    and diary pages. Same provider gate: real photographed customer data is exactly
    as sensitive as a real transcript and must not touch the free Gemini tier
    either."""
    return try_models(
        lambda model: _first_json(
            _raw_completion(system, user, max_tokens, image_bytes=image_bytes,
                            mime_type=mime_type, model=model)
        )
    )


def transcribe_audio(audio_bytes: bytes, mime_type: str,
                     names: "list[str] | None" = None) -> str:
    """Transcribe a voice note to text via Gemini's native audio understanding.

    Always Gemini, regardless of EXTRACTION_PROVIDER - Anthropic's API has no
    audio input, so there is no 'anthropic' path here the way there is for
    complete_json/complete_json_with_image. A real voice note is exactly as
    sensitive as a real transcript; if EXTRACTION_PROVIDER is later set to
    'anthropic' for that reason, transcription itself still touches Gemini
    until this function is pointed at a paid Gemini key or another audio-
    capable provider."""
    return try_models(lambda model: _raw_transcribe(audio_bytes, mime_type, model=model, names=names))


def _raw_transcribe(audio_bytes: bytes, mime_type: str, *, model: str = "",
                    names: "list[str] | None" = None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=model or _GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            "Transcribe this audio verbatim, in whatever language(s) are spoken. "
            "Return only the transcript text - no commentary, no timestamps, no speaker labels."
            + vocabulary_hint(names),
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


# Google answers 503 UNAVAILABLE ("this model is currently experiencing high
# demand") and 500 INTERNAL when its own capacity is short. Both are the API
# asking to be called again shortly, and neither is a rate limit - so they fell
# through to `raise` and killed the message on the first attempt. That is how a
# real voice note was lost: transcription was refused once and never retried.
# Matched on the exception class and on the text, so it holds for either
# provider and for a wrapper that loses the class.
_TRANSIENT_TEXT = re.compile(
    r"UNAVAILABLE|INTERNAL|overloaded|high demand|try again later|"
    r"50[0234] (?:Bad Gateway|Internal|Service|Gateway)",
    re.IGNORECASE,
)

_TRANSIENT_TYPES = (
    "ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError",
    "ServerError",                                      # google-genai 5xx
    "InternalServerError", "APIConnectionError", "APITimeoutError",
    "OverloadedError",                                  # anthropic
)


def _is_transient(exc: Exception) -> bool:
    return type(exc).__name__ in _TRANSIENT_TYPES or bool(_TRANSIENT_TEXT.search(str(exc)))


def with_retries(call):
    """Retry what the provider itself calls temporary: connection resets,
    capacity errors (503/500), and rate limits short enough to wait out.
    Shared by every model call - the extraction and transcription passes
    included, since those are the ones a lost voice note dies on."""
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return call()
        except (ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            delay = 1.5 * (attempt + 1)
        except Exception as exc:  # httpx/httpcore connect errors don't subclass the stdlib ones
            asked = _retry_after(exc)
            if asked is None and not _is_transient(exc):
                raise
            last_exc = exc
            # A capacity spike needs longer than a dropped connection, and
            # doubling costs nothing on a call that is going to fail anyway.
            delay = asked if asked is not None else 2.0 * (2 ** attempt)
        if attempt < _RETRIES - 1:
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


_with_retries = with_retries  # the name the calls in this module already use


def _raw_completion(system: str, user: str, max_tokens: int, *, image_bytes: bytes | None = None, mime_type: str | None = None, model: str = "") -> str:
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
            model=model or _GEMINI_MODEL,
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
