import os

from app.extraction.schema import ExtractionResult
from app.extraction.verify import verify

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()


def _raw_extract(transcript: str) -> ExtractionResult:
    if PROVIDER == "anthropic":
        from app.extraction.providers.anthropic_provider import extract as fn
    elif PROVIDER == "gemini":
        from app.extraction.providers.gemini_provider import extract as fn
    else:
        raise ValueError(f"Unknown EXTRACTION_PROVIDER: {PROVIDER!r}")
    return fn(transcript)


def extract(transcript: str) -> ExtractionResult:
    """Extraction pass, then a verification pass that grounds every item in a
    verbatim transcript quote and demotes anything it can't ground."""
    result = _raw_extract(transcript)
    return verify(transcript, result)
