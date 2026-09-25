"""Is an incoming WhatsApp message a note to log, or a question to answer?

The uncle records between meetings, on the road, 250 days a year. Requiring him
to remember a keyword means the day he forgets it, his question is filed as a
meeting - which is exactly what happened the first time he asked for a summary.

So the message is classified instead, and the tie is broken toward logging: a
question filed as a note costs a junk row someone deletes, while a note answered
as a question loses a real meeting that nobody knows went missing. Anything the
model is unsure about, and every failure of this call, is therefore a note.
"""

from app.llm import complete_json

_SYSTEM = """You decide whether a message sent to a sales CRM is a NOTE or a QUESTION.

NOTE: the sender is recording something that happened, so it can be filed - a visit,
a call, a meeting, an instruction for the team, anything with facts to keep.
Examples: "Met Rajesh at Parag Foods today, they need two level transmitters."
"Tell Vishal to call him on Monday." "Internal meeting, we set the target at 7 crore."

QUESTION: the sender wants information back out of the CRM, and there is nothing in
the message worth filing.
Examples: "What's pending with Thermo?" "Give me a summary of what you recorded."
"Who is Priya Nair?" "Brief me on Gujarat Ambuja."

Answer with {"kind": "note"} or {"kind": "question"}. When the message contains
anything worth filing, or you are unsure, answer "note"."""


def is_question(text: str) -> bool:
    """True only when the message is clearly a question and nothing else.
    Never raises: a classification failure falls back to filing the message."""
    body = (text or "").strip()
    if not body:
        return False
    try:
        answer = complete_json(_SYSTEM, body, max_tokens=32)
    except Exception:
        return False
    if isinstance(answer, list):
        answer = answer[0] if answer else {}
    if not isinstance(answer, dict):
        return False
    return str(answer.get("kind", "")).strip().lower() == "question"
