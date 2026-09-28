import os

from google import genai

from app.extraction.prompt import build_system_prompt
from app.extraction.schema import ExtractionResult

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def extract(transcript: str, roster: list[str], *, model: str = "") -> ExtractionResult:
    """`model` is supplied by the caller's fallback loop - the free tier's small
    models run out of spare capacity first, and a refused extraction used to
    lose the note outright."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    response = client.models.generate_content(
        model=model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=transcript,
        config={
            "system_instruction": build_system_prompt(roster),
            "response_mime_type": "application/json",
            "response_schema": ExtractionResult,
            "temperature": 0,
        },
    )

    return ExtractionResult(**response.parsed.model_dump())
