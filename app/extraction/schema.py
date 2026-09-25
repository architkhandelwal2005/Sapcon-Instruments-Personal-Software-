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


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class RelativeDue(BaseModel):
    """Either an offset ("next week" -> amount 1, unit "week") or a named day
    ("on Monday" -> weekday "monday"), never both. A named day has no honest
    offset - "Monday" said on a Friday is 3 days out, not 7 - so squeezing it
    into amount/unit is what produced wrong due dates."""

    amount: Optional[int] = None
    unit: Optional[Literal["day", "week", "month"]] = None
    weekday: Optional[Weekday] = None


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
    assignees: list[str] = []         # staff explicitly named to do it; empty if nobody was named
    relative_due: Optional[RelativeDue] = None
    confidence: Confidence
    source_quote: Optional[str] = None   # filled by the verification pass


class ExtractedDecision(BaseModel):
    description: str                  # one standalone sentence, numbers exact
    confidence: Confidence
    source_quote: Optional[str] = None   # filled by the verification pass


MeetingKind = Literal["field_visit", "internal"]


class ExtractionResult(BaseModel):
    kind: MeetingKind
    attendees: list[str]              # staff present (internal meetings); names as on the roster
    entities: list[ExtractedEntity]
    connections: list[ExtractedConnection]
    decisions: list[ExtractedDecision]
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
                            "assignees": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "staff explicitly named to do it",
                            },
                            "relative_due": {
                                "type": "object",
                                "description": (
                                    "an offset (amount + unit) OR a named day (weekday), never both"
                                ),
                                "properties": {
                                    "amount": {"type": "integer"},
                                    "unit": {"type": "string", "enum": ["day", "week", "month"]},
                                    "weekday": {"type": "string", "enum": WEEKDAYS},
                                },
                            },
                            "confidence": conf,
                        },
                        "required": ["description", "confidence"],
                    },
                },
                "decisions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "confidence": conf,
                        },
                        "required": ["description", "confidence"],
                    },
                },
                "kind": {"type": "string", "enum": ["field_visit", "internal"]},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["kind", "attendees", "entities", "connections", "decisions", "tasks", "summary"],
        },
    }
