import os

from app.extraction.schema import ExtractionResult

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()


def extract(transcript: str) -> ExtractionResult:
    if PROVIDER == "anthropic":
        from app.extraction.providers.anthropic_provider import extract as _extract
    elif PROVIDER == "gemini":
        from app.extraction.providers.gemini_provider import extract as _extract
    else:
        raise ValueError(f"Unknown EXTRACTION_PROVIDER: {PROVIDER!r}")

    return _extract(transcript)
