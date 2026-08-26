import anthropic

from app.extraction.prompt import build_system_prompt
from app.extraction.schema import TOOL_NAME, ExtractionResult, build_tool_schema

MODEL = "claude-haiku-4-5-20251001"


def extract(transcript: str) -> ExtractionResult:
    client = anthropic.Anthropic()
    tool = build_tool_schema()

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=build_system_prompt(),
        tools=[tool],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": transcript}],
    )

    for block in response.content:
        if block.type == "tool_use":
            return ExtractionResult(**block.input)

    raise RuntimeError("Model response did not include a tool_use block")
