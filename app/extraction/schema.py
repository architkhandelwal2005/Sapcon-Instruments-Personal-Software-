from typing import Literal, Optional

from pydantic import BaseModel, create_model

from app.extraction.prompt import load_relation_types

TOOL_NAME = "record_extraction"

ENTITY_TYPES = ["person", "company", "site"]


class RelativeDue(BaseModel):
    amount: int
    unit: Literal["day", "week", "month"]


class ExtractedEntity(BaseModel):
    name: str
    entity_type: Literal["person", "company", "site"]


class ExtractedTriple(BaseModel):
    source: str
    relation: str
    target: str
    provenance: Literal["direct", "hearsay"]


class ExtractedTask(BaseModel):
    description: str
    target_entity: Optional[str] = None
    relative_due: Optional[RelativeDue] = None


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity]
    relationships: list[ExtractedTriple]
    tasks: list[ExtractedTask]


def build_dynamic_result_model() -> type[BaseModel]:
    """A pydantic model class equivalent to ExtractionResult, but with
    `relation` constrained to a Literal built fresh from config/relation_types.yaml.
    Used as the response_schema for providers (e.g. Gemini) that accept a
    pydantic model directly for schema-constrained output, so the vocabulary
    stays a one-line config change there too. Convert the result back to
    ExtractionResult via ExtractionResult(**result.model_dump()) so callers
    only ever deal with the stable public models."""
    relation_types = load_relation_types()
    relation_literal = Literal[tuple(relation_types)]  # type: ignore[valid-type]

    dynamic_triple = create_model(
        "DynamicExtractedTriple",
        source=(str, ...),
        relation=(relation_literal, ...),
        target=(str, ...),
        provenance=(Literal["direct", "hearsay"], ...),
    )
    return create_model(
        "DynamicExtractionResult",
        entities=(list[ExtractedEntity], ...),
        relationships=(list[dynamic_triple], ...),
        tasks=(list[ExtractedTask], ...),
    )


def build_tool_schema() -> dict:
    """JSON schema for the forced tool-use call. Relation vocabulary is read
    from config/relation_types.yaml at call time — swap that file, not this
    function, to change the vocabulary."""
    relation_types = load_relation_types()
    return {
        "name": TOOL_NAME,
        "description": "Record entities, relationship triples, and tasks extracted from the meeting transcript.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "description": (
                        "Every distinct entity mentioned anywhere in the output below (as a "
                        "relationship source/target or a task's target_entity), listed exactly "
                        "once each with its type."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "entity_type": {"type": "string", "enum": ENTITY_TYPES},
                        },
                        "required": ["name", "entity_type"],
                    },
                },
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "description": "Name of the entity the relation originates from",
                            },
                            "relation": {"type": "string", "enum": relation_types},
                            "target": {
                                "type": "string",
                                "description": "Name of the entity the relation points to",
                            },
                            "provenance": {
                                "type": "string",
                                "enum": ["direct", "hearsay"],
                            },
                        },
                        "required": ["source", "relation", "target", "provenance"],
                    },
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "target_entity": {
                                "type": "string",
                                "description": "Entity this task relates to, if any",
                            },
                            "relative_due": {
                                "type": "object",
                                "description": "Due date relative to the meeting date, if one was mentioned",
                                "properties": {
                                    "amount": {"type": "integer"},
                                    "unit": {"type": "string", "enum": ["day", "week", "month"]},
                                },
                                "required": ["amount", "unit"],
                            },
                        },
                        "required": ["description"],
                    },
                },
            },
            "required": ["entities", "relationships", "tasks"],
        },
    }
