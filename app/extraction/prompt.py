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

   For each triple, mark provenance. Provenance answers exactly one question - is the informant \
speaking firsthand, or relaying a claim someone else made? It is a completely separate question \
from whether the fact itself is certain, settled, or has already happened. NEVER use provenance to \
encode uncertainty — a firsthand claim about a tentative future plan is still "direct", not \
"hearsay", just because the plan hasn't happened yet.
   - "direct": someone present in this meeting has firsthand knowledge of the fact — e.g. they are \
describing their own company, their own customers, partners, or contractors, or something they \
personally witnessed. Two things do NOT disqualify a fact from being direct: (1) the other entity \
in the relation does not need to be present itself, and (2) the fact does not need to be settled, \
confirmed, or already true.
     Example: Rajesh (present, owner of Indocem) says Ambuja Cement is one of Indocem's end users. \
Ambuja itself isn't present, but Rajesh has firsthand knowledge of his own company's customers — \
direct.
     Example: Suresh (present) says his own workshop is thinking about becoming an end user of a \
product line. This is direct — Suresh has firsthand knowledge of his own company's plans — even \
though the plan itself is tentative and hasn't happened yet. Do not mark this hearsay just because \
it's uncertain.
   - "hearsay": the speaker is relaying a claim from a third party who is NOT present in this \
meeting and not personally involved in the fact being described, which the speaker has not \
independently verified.
     Example: Rajesh relays that he heard from an unnamed contact at a trade fair that "Shree \
Distributors might become a distributor" for Sapcon. Rajesh has no firsthand knowledge of Shree \
Distributors' own plans — he's relaying an unverified third-party claim — hearsay.
   Extract relations even when they describe something tentative, aspirational, or not yet \
confirmed (e.g. "might become", "trying to", "is thinking about") — never omit a relation just \
because it describes a possibility rather than a settled fact. This applies equally to direct and \
hearsay relations; tentativeness never changes which provenance value to use.

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
