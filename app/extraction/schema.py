from typing import Literal, Optional

from pydantic import BaseModel

TOOL_NAME = "record_extraction"

Confidence = Literal["high", "medium", "low"]
EntityType = Literal["person", "company", "site"]
Provenance = Literal["direct", "hearsay"]

# Suggested role tags for connections - offered to the model as a hint, NOT
# enforced. The model may use its own word, leave it null, or the office boy
# edits it later. Nothing branches on this value.
SUGGESTED_ROLES = ["consultant", "advisory", "oem", "end_user", "employer", "competitor", "referral"]


class RelativeDue(BaseModel):
    amount: int
    unit: Literal["day", "week", "month"]


class ExtractedEntity(BaseModel):
    name: str
    entity_type: EntityType
    title: Optional[str] = None       # designation/department, if stated
    phone: Optional[str] = None
    email: Optional[str] = None
    region: Optional[str] = None      # zone/state, if stated
    confidence: Confidence


class ExtractedConnection(BaseModel):
    source: str                       # entity name the connection is from
    target: str                       # entity name the connection is to
    description: str                  # plain-language sentence stating the connection
    suggested_role: Optional[str] = None
    provenance: Provenance
    confidence: Confidence
    source_quote: Optional[str] = None   # filled by the verification pass, not the extraction model


class ExtractedTask(BaseModel):
    description: str
    target_entity: Optional[str] = None
    assignee: Optional[str] = None    # employee name, only if the speaker explicitly named one
    relative_due: Optional[RelativeDue] = None
    confidence: Confidence
    source_quote: Optional[str] = None   # filled by the verification pass


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    connections: list[ExtractedConnection]
    tasks: list[ExtractedTask]
    summary: str                      # clean prose recap of the meeting


def build_tool_schema() -> dict:
    """Anthropic forced-tool-use schema. Mirrors ExtractionResult. No enum on
    role - it's a free string hint only."""
    conf = {"type": "string", "enum": ["high", "medium", "low"]}
    return {
        "name": TOOL_NAME,
        "description": "Record entities, connections, tasks, and a summary extracted from the meeting transcript.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "entity_type": {"type": "string", "enum": ["person", "company", "site"]},
                            "title": {"type": "string"},
                            "phone": {"type": "string"},
                            "email": {"type": "string"},
                            "region": {"type": "string"},
                            "confidence": conf,
                        },
                        "required": ["name", "entity_type", "confidence"],
                    },
                },
                "connections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "description": {"type": "string", "description": "plain-language sentence"},
                            "suggested_role": {"type": "string"},
                            "provenance": {"type": "string", "enum": ["direct", "hearsay"]},
                            "confidence": conf,
                        },
                        "required": ["source", "target", "description", "provenance", "confidence"],
                    },
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "target_entity": {"type": "string"},
                            "assignee": {"type": "string", "description": "employee name, only if explicitly named"},
                            "relative_due": {
                                "type": "object",
                                "properties": {
                                    "amount": {"type": "integer"},
                                    "unit": {"type": "string", "enum": ["day", "week", "month"]},
                                },
                                "required": ["amount", "unit"],
                            },
                            "confidence": conf,
                        },
                        "required": ["description", "confidence"],
                    },
                },
                "summary": {"type": "string"},
            },
            "required": ["entities", "connections", "tasks", "summary"],
        },
    }
