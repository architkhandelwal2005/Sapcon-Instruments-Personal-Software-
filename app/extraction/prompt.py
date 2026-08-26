from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "relation_types.yaml"

SYSTEM_PROMPT_TEMPLATE = """You are extracting structured data from the transcript of a field-sales \
meeting recap. The speaker is a salesperson for Sapcon Instruments, an Indian manufacturer of \
level and speed-monitoring instruments sold through channel partners to process industries \
(cement, steel, pharma, dairy, fertilizer).

Extract three things:

0. Every distinct entity mentioned anywhere in your output below (as a relationship source/target, \
or a task's target_entity) — list each one exactly once, with its type: "person", "company", or \
"site". Use the same exact name spelling everywhere you reference that entity in this response.

1. Relationship triples between entities (people, companies, or sites) mentioned in the transcript.
   Each triple has a source, a relation type, and a target. Getting the DIRECTION right matters — \
source and target are not interchangeable, and each relation type below has exactly one correct \
direction:

{relation_type_guide}

   Do not emit the same underlying fact as two mirrored triples (for example both "A distributor_for \
B" and "B end_user_of A" describing the same relationship) — pick the single relation type and \
direction that best matches what was actually stated, and emit it once.

   For each triple, mark provenance based on whether the INFORMATION is firsthand, not on whether \
every entity named in the triple was physically present:
   - "direct": someone present in this meeting has firsthand knowledge of the fact — e.g. they are \
describing their own company, their own customers, partners, or contractors, or something they \
personally witnessed. The other entity in the relation (e.g. a customer being described) does not \
need to be present itself for this to count as direct.
   - "hearsay": the speaker is relaying a claim from someone who is not present in this meeting and \
not personally involved, which the speaker has not independently verified (e.g. "I heard from \
someone that X might become a distributor"). Extract hearsay relations even when they describe \
something tentative or not yet confirmed (e.g. "might become", "trying to", "could end up") — that \
uncertainty is exactly what "hearsay" is for. Do not omit a relation just because it describes a \
possibility rather than an established fact.

2. Tasks or commitments the speaker mentioned needing to do. For each task, extract:
   - description: what needs to be done
   - target_entity: the entity the task relates to, if any
   - relative_due: if a due date was mentioned relative to today (e.g. "in two weeks", "by next \
month"), extract it as an amount and a unit (day, week, or month). Do NOT compute an absolute \
date yourself — just extract the amount and unit as stated. Omit relative_due entirely if no \
timeframe was mentioned.

Only extract what is actually stated or clearly implied in the transcript. Do not invent entities \
or relationships that aren't mentioned.
"""


def load_relation_type_specs() -> list[dict]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["relation_types"]


def load_relation_types() -> list[str]:
    return [spec["name"] for spec in load_relation_type_specs()]


def _format_relation_type_guide(specs: list[dict]) -> str:
    lines = [f'   - {spec["name"]}: {spec["description"]} Example: "{spec["example"]}"' for spec in specs]
    return "\n".join(lines)


def build_system_prompt() -> str:
    specs = load_relation_type_specs()
    return SYSTEM_PROMPT_TEMPLATE.format(relation_type_guide=_format_relation_type_guide(specs))
