"""What is this WhatsApp message for: filing, answering, or nothing at all?

The uncle records between meetings, on the road, 250 days a year. Requiring him
to remember a keyword means the day he forgets it, his question is filed as a
meeting - which is exactly what happened the first time he asked for a summary.
So the message is classified rather than prefixed.

There are three answers, not two. "Thanks", "ok", "hi" are neither a note nor a
question, and filing them ran the whole pipeline over one word: a model call, a
failed extraction, an error row, and a confusing reply. A chat people actually
talk in is full of those.

Which way a doubt falls depends on what the mistake costs:

- Between note and question, toward the note. A question filed as a note costs
  a junk row someone deletes; a note answered as a question loses a real
  meeting nobody knows went missing.
- Toward NOTHING only when there is almost nothing to lose. The model's
  "nothing" is taken for a short message and refused for a long one, because a
  long message discarded is a visit gone, while a long acknowledgement is not a
  thing people send. Every failure of the call is a note.
"""

import re

from app.llm import complete_json

Intent = str  # "note" | "question" | "nothing"

# A message this short cannot be a visit recap, so it is the only kind we let a
# model throw away. Roughly a line of chat.
MAX_NOTHING_CHARS = 120

# The everyday ones, settled without spending a model call. Most messages after
# a readback are one of these, and against a 500-a-day free tier that is the
# difference between paying for politeness and not.
_ACK_WORDS = {
    "thanks", "thank", "thankyou", "ty", "thx", "tx",
    "ok", "okay", "okey", "k", "kk", "fine", "good", "great", "nice", "perfect",
    "got", "it", "sure", "right", "correct", "yes", "yeah", "yep", "yup", "no",
    "noted", "understood", "received", "cool", "super", "excellent", "welcome",
    "u", "you", "so", "much", "very", "well", "all", "clear", "hi", "hello",
    "hey", "namaste", "morning", "afternoon", "evening", "night", "bye",
    "haan", "han", "theek", "thik", "hai", "achha", "acha", "accha",
    "shukriya", "dhanyavad", "bilkul", "sahi", "hmm", "hm", "hmmm",
    "ji", "bhai", "sir", "done",      # "done" alone is agreement, not a command:
                                      # a real instruction names what is done,
                                      # and the command parser has already run.
}

_WORD = re.compile(r"[a-z]+")

# An emoji, a tick, a full stop - nothing a person could mean as a record.
_NO_LETTERS = re.compile(r"^[\W\d_]+$", re.UNICODE)


def is_acknowledgement(text: str) -> bool:
    """A short courtesy with nothing in it to keep, decided without a model.

    Deliberately narrow: every word has to be a known one, so "thanks, also met
    Rajesh today" is not an acknowledgement and is filed normally. Being wrong
    here means dropping something, so it only fires on messages made entirely
    of these words."""
    body = (text or "").strip()
    if not body or len(body) > 40:
        return False
    if _NO_LETTERS.match(body):          # an emoji or a tick on its own
        return True
    words = _WORD.findall(body.lower())
    return bool(words) and len(words) <= 5 and all(w in _ACK_WORDS for w in words)


_SYSTEM = """You decide what a message sent to a sales CRM is for.

NOTE: the sender is recording something that happened, so it can be filed - a visit,
a call, a meeting, an instruction for the team, anything with facts to keep.
Examples: "Met Rajesh at Parag Foods today, they need two level transmitters."
"Tell Vishal to call him on Monday." "Internal meeting, we set the target at 7 crore."

QUESTION: the sender wants information back out of the CRM, or wants to know what
this system can do, and there is nothing in the message worth filing.
Examples: "What's pending with Thermo?" "Give me a summary of what you recorded."
"Who is Priya Nair?" "Brief me on Gujarat Ambuja." "What can you do?"

NOTHING: small talk, thanks, agreement, a greeting, a test - it asks for nothing and
records nothing, so there is no work to do.
Examples: "thanks" "ok got it" "great, will do" "hello" "testing" "haan theek hai"

Answer with {"kind": "note"}, {"kind": "question"} or {"kind": "nothing"}.
If the message contains ANYTHING worth filing, answer "note", even alongside small
talk - "thanks, also met Rajesh today" is a note. When unsure, answer "note"."""


def classify(text: str) -> Intent:
    """What to do with this message. Never raises: a failed call is a note, so
    a message is filed rather than lost."""
    body = (text or "").strip()
    if not body:
        return "nothing"
    if is_acknowledgement(body):
        return "nothing"
    try:
        answer = complete_json(_SYSTEM, body, max_tokens=32)
    except Exception:
        return "note"
    if isinstance(answer, list):
        answer = answer[0] if answer else {}
    if not isinstance(answer, dict):
        return "note"

    kind = str(answer.get("kind", "")).strip().lower()
    if kind == "question":
        return "question"
    if kind == "nothing" and len(body) <= MAX_NOTHING_CHARS:
        return "nothing"
    return "note"


def is_question(text: str) -> bool:
    """True only when the message is clearly a question and nothing else."""
    return classify(text) == "question"
