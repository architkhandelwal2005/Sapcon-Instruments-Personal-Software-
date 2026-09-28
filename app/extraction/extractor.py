import os

from app.extraction.schema import ExtractionResult
from app.extraction.verify import verify
from app.llm import try_models, with_retries

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "gemini").lower()


def _raw_extract(transcript: str, roster: list[str]) -> ExtractionResult:
    if PROVIDER == "anthropic":
        from app.extraction.providers.anthropic_provider import extract as fn

        # One model, so retries are all there is to fall back on.
        return with_retries(lambda: fn(transcript, roster))
    if PROVIDER == "gemini":
        from app.extraction.providers.gemini_provider import extract as fn

        # Retries, then a bigger model when the small one is out of free
        # capacity. This pass refusing used to lose the whole voice note.
        return try_models(lambda model: fn(transcript, roster, model=model))
    raise ValueError(f"Unknown EXTRACTION_PROVIDER: {PROVIDER!r}")


def extract(transcript: str, roster: list[str]) -> ExtractionResult:
    """Extraction pass, then a verification pass that grounds every item in a
    verbatim transcript quote and demotes anything it can't ground. `roster` is
    the staff name list, so the model spells staff consistently and keeps them
    out of the external-entity graph."""
    result = _raw_extract(transcript, roster)
    return verify(transcript, result)
