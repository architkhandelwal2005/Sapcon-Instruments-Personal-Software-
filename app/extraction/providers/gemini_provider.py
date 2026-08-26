import os

from google import genai

from app.extraction.prompt import build_system_prompt
from app.extraction.schema import ExtractionResult, build_dynamic_result_model

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def extract(transcript: str) -> ExtractionResult:
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    dynamic_result_model = build_dynamic_result_model()

    response = client.models.generate_content(
        model=model,
        contents=transcript,
        config={
            "system_instruction": build_system_prompt(),
            "response_mime_type": "application/json",
            "response_schema": dynamic_result_model,
            "temperature": 0,
        },
    )

    return ExtractionResult(**response.parsed.model_dump())
