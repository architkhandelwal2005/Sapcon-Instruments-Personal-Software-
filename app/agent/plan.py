"""Decide what a message wants, in the context of the conversation so far.

This replaces a ladder of keyword checks - is it a correction, is it a command,
is it a question, otherwise file it - which could only recognise three
instructions and turned everything else into a meeting. A greeting became a
meeting. "What can you do?" became a meeting.

One call now does the whole decision, and it costs less than the two calls the
ladder often made. What the model returns is an intent and the sender's own
words, never a database row: which task "the Rakesh one" means is still decided
in SQL afterwards, where two matches can be counted and refused. The model says
what the person wants; the database says what exists. That division is the only
reason an instruction cannot quietly change the wrong record.

The model also writes the reply for anything that is pure conversation - a
greeting, a question about the system itself, a refusal it needs to explain.
Anything carrying data - a readback, an answer from records, the result of a
change - is still formatted deterministically, because those must not be
paraphrased.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.llm import complete_json

Action = Literal[
    "log",          # record what happened
    "ask",          # answer from the CRM
    "assign_task",
    "complete_task",
    "drop_lead",
    "undo",
    "chat",         # small talk, help, a clarifying question - reply and stop
]

_ACTIONS = {"log", "ask", "assign_task", "complete_task", "drop_lead", "undo", "chat"}

# A long message is never treated as chat, however conversational it reads. A
# long message answered with a pleasantry is a visit thrown away; a long
# greeting is not a thing people send.
MAX_CHAT_CHARS = 200

# The everyday courtesies, settled before the model is asked. Most replies to a
# readback are one of these, and against a free tier capped at 500 calls a day
# that is the difference between paying for politeness and not. It also means a
# greeting still costs nothing on the day the model is refusing calls.
_ACK_WORDS = {
    "thanks", "thank", "thankyou", "ty", "thx", "tx",
    "ok", "okay", "okey", "k", "kk", "fine", "good", "great", "nice", "perfect",
    "got", "it", "sure", "right", "correct", "yes", "yeah", "yep", "yup", "no",
    "noted", "understood", "received", "cool", "super", "excellent", "welcome",
    "u", "you", "so", "much", "very", "well", "all", "clear",
    "hi", "hello", "hey", "namaste", "morning", "afternoon", "evening", "bye",
    "haan", "han", "theek", "thik", "hai", "achha", "acha", "accha",
    "shukriya", "dhanyavad", "bilkul", "sahi", "hmm", "hm", "hmmm", "ji",
}

_WORD = re.compile(r"[a-z]+")
_NO_LETTERS = re.compile(r"^[\W\d_]+$", re.UNICODE)   # an emoji or a tick alone


def is_courtesy(text: str) -> bool:
    """A short pleasantry with nothing in it to keep or look up.

    Deliberately narrow: every word must be a known one, so "thanks, also met
    Rajesh today" is not a courtesy and goes to the model like anything else.
    Being wrong here means dropping a message, so it only fires on ones made
    entirely of these words."""
    body = (text or "").strip()
    if not body or len(body) > 40:
        return False
    if _NO_LETTERS.match(body):
        return True
    words = _WORD.findall(body.lower())
    return bool(words) and len(words) <= 5 and all(w in _ACK_WORDS for w in words)


@dataclass
class Plan:
    action: Action
    target: str = ""            # the words naming a task or lead, as spoken
    person: str = ""            # who a task should go to
    question: str = ""          # the question to answer, as asked
    reply: str = ""             # what to say, for "chat" only


_SYSTEM = """You are the assistant behind a sales CRM that a company's sales head talks
to on WhatsApp. He is on the road most of the year. He sends voice notes after customer
visits, asks about people and pending work, and tells you to change things. He types and
speaks in Indian English, often mixing in Hindi.

Decide what his latest message wants. Use the conversation so far to understand
follow-ups: "and Parag?" after a question about another customer is the same question
about Parag.

Actions:

- "log": he is recording something that happened - a visit, a call, a meeting, a new
  contact, an instruction for his team to do something new. Anything with facts worth
  keeping. This is the default for anything substantial.
- "ask": he wants information back out of the CRM - about a person, a company, pending
  work, what happened somewhere, someone's number, a summary.
- "assign_task": give an EXISTING task an owner. Needs "person".
- "complete_task": mark an EXISTING task finished.
- "drop_lead": stop pursuing a lead.
- "undo": reverse the change you just made.
- "chat": greeting, thanks, agreement, a question about you or what you can do, or
  anything with nothing to record and nothing to look up. You write the reply.

Return JSON:
{"action": "<one of the above>",
 "target": "<for the three change actions: his words naming the task or lead>",
 "person": "<for assign_task: who it goes to>",
 "question": "<for ask: the question, rewritten to stand alone if it was a follow-up>",
 "reply": "<for chat only: what to say back>"}

Rules that matter:
- Telling you about a NEW thing to do ("tell Vishal to call him Monday") is "log", not
  assign_task. The three change actions only ever refer to something already recorded.
- Small talk wrapped around real content is "log": "thanks, also met Rajesh today" is a
  log, not chat.
- When you genuinely cannot tell what he wants, use "chat" and ask him a short question
  back. Never guess between changing two different things.
- If in doubt between "log" and anything else, choose "log". A note filed wrongly is a
  row someone deletes; a note treated as a question is a visit lost.

For "chat" replies: sound like a capable assistant who knows this business, not a
chatbot. Short - one or two lines, this is WhatsApp. No greetings back unless he
greeted you. Never claim to have done something you have not done. If he asks what you
can do, say: log visits from voice notes or text, answer questions about people,
companies, pending work and past meetings, and carry out changes - assign a task to
someone, mark one done, drop a lead."""


def plan_message(text: str, conversation: str) -> Plan:
    """What this message wants. Never raises: a failed call falls back to
    logging, so a real note is filed rather than lost."""
    body = (text or "").strip()
    if not body:
        return Plan(action="chat", reply="")
    if is_courtesy(body):
        # Nothing to record, nothing to look up, and nothing worth saying back:
        # a reply to "thanks" only invites another "ok".
        return Plan(action="chat", reply="")

    user = f"Conversation so far:\n{conversation}\n\nHis latest message:\n{body}"
    try:
        raw = complete_json(_SYSTEM, user, max_tokens=400)
    except Exception:
        return Plan(action="log")
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict):
        return Plan(action="log")

    action = str(raw.get("action") or "").strip().lower()
    if action not in _ACTIONS:
        return Plan(action="log")

    plan = Plan(
        action=action,                                      # type: ignore[arg-type]
        target=str(raw.get("target") or "").strip(),
        person=str(raw.get("person") or "").strip(),
        question=str(raw.get("question") or "").strip() or body,
        reply=str(raw.get("reply") or "").strip(),
    )

    # A change action with nothing to match on cannot be carried out, and
    # guessing which row was meant is the one thing never allowed here.
    if plan.action in ("assign_task", "complete_task", "drop_lead") and not plan.target:
        return Plan(action="log")
    if plan.action == "assign_task" and not plan.person:
        return Plan(action="log")
    # Chat is the only action that discards the message, so it is bounded.
    if plan.action == "chat" and len(body) > MAX_CHAT_CHARS:
        return Plan(action="log")
    return plan
