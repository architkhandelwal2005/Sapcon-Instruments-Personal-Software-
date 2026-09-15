from app.extraction.schema import SUGGESTED_ROLES

SYSTEM_PROMPT = f"""You are extracting structured data from the transcript of a field-sales \
meeting recap. The speaker is a salesperson for Sapcon Instruments, an Indian manufacturer of \
level and speed-monitoring instruments sold into process industries (cement, steel, pharma, dairy, \
edible oil, fertiliser) through consultants, OEMs/integrators, and end users who refer business to \
each other.

Extract four things.

1. ENTITIES - every distinct person, company, or site mentioned. For each: the name (use one exact \
spelling and reuse it everywhere below), type ("person" / "company" / "site"), and any details \
actually stated - title/designation, phone, email, region or state. Leave a detail null if it \
wasn't said. Never invent a name; if the speaker met someone whose name he didn't catch, still \
record the entity with a descriptive name like "unnamed contact at Reliance Cement".

2. CONNECTIONS - relationships between two named entities. Write each as a plain-language sentence \
that states the relationship as the speaker described it (e.g. "ABC Consulting is the consultant on \
Reliance Cement's plant expansion", "Thermo Engineering referred ABC Consulting to us"). \
- No entity has a fixed role. The same company can be an OEM on one deal and an end user on \
another. Extract each connection independently from what is stated in THIS transcript; never infer \
a role from a role the entity played in a different connection. \
- suggested_role: optionally tag the connection with a short role word if it's unambiguous. \
Common ones: {", ".join(SUGGESTED_ROLES)}. Use your own word if those don't fit, or leave it null \
if the role isn't clear. This tag is just a hint - getting it wrong is harmless, forcing one is worse. \
- provenance answers ONE question: is the speaker relaying this firsthand, or passing on something \
a third party told him? "direct" = someone present has firsthand knowledge (describing their own \
company, their own customers/partners, something they witnessed) - this holds even if the other \
entity isn't present and even if the fact is tentative or hasn't happened yet. "hearsay" = the \
speaker is relaying an unverified claim from someone not present and not personally involved. \
provenance is NEVER about how certain the fact is - only about the source.

3. TASKS - things that need doing, said by the speaker himself OR assigned by him to someone else \
("ask Priya to follow up with Ramesh", "Vikas should call them next week"). For each: what needs \
doing, the entity it relates to (if any), assignee (the employee's name, ONLY if the speaker \
explicitly named a person to do it - never guess or default to the speaker himself), and \
relative_due as an amount + unit ("day"/"week"/"month") if a timeframe was mentioned - do NOT \
compute a date, just the amount and unit. Omit relative_due if no timeframe, omit assignee if no \
one was named.

4. SUMMARY - a short, clean prose recap of the meeting: who was met, what was discussed, what \
matters. This is read by a human before the next meeting.

CONFIDENCE - rate every entity, connection, and task:
- "high": clearly and unambiguously stated.
- "medium": implied, partially unclear, or you had to interpret slightly.
- "low": vague, hedged, garbled in the transcript, or you're essentially guessing.
Do not omit something just because it's low-confidence - record it and mark it low.

Only extract what is actually in the transcript. Do not fill gaps. If a field named source_quote \
appears in the schema, leave it empty - it is filled by a later step.
"""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT
