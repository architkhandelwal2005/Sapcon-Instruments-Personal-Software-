"""WhatsApp-sized reply formatters - short, built from counts the pipelines
already return, not a dump of the full read-back (the sender already has the
audio/photo they just sent; the long formatter is for the web meeting page).
"""

import re

from app.capture.pipeline import CaptureResult
from app.ingestion.pipeline import IngestResult
from app.query import AskResult

_MAX_LEN = 1500  # comfortably under WhatsApp/Twilio's message size limit


def meeting_reply(result: IngestResult, meeting_url: str) -> str:
    bits = []
    if result.decision_count:
        bits.append(f"{result.decision_count} decisions")
    if result.entity_count:
        bits.append(f"{result.entity_count} people/companies")
    if result.connection_count:
        bits.append(f"{result.connection_count} connections")
    if result.task_count:
        bits.append(f"{result.task_count} tasks")
    summary = ", ".join(bits) if bits else "nothing extracted"
    lines = [f"Logged - {summary}."]
    if result.pending:
        lines.append(f"{result.pending} item(s) need a quick check.")
    lines.append(meeting_url)
    return "\n".join(lines)


def capture_reply(result: CaptureResult, capture_type: str, review_url: str) -> str:
    if result.item_count == 0:
        return f"Got the {capture_type} photo but couldn't read anything on it - try a clearer shot."
    lines = [f"Logged {result.item_count} {capture_type} item(s)."]
    assigned = sum(1 for r in result.resolved if r.assigned_to)
    unassigned = sum(1 for r in result.resolved if r.lead_id and not r.assigned_to)
    if assigned:
        lines.append(f"{assigned} assigned by the circled initials.")
    if unassigned:
        lines.append(f"{unassigned} need manual allotment (no matching initials).")
    if result.pending:
        lines.append(f"{result.pending} item(s) need a quick check.")
    lines.append(review_url)
    return "\n".join(lines)


# Reference markers belong in the citations list, where the website renders
# them as links to the row. Sent to a phone they are noise - a real answer came
# back reading "Call Priya back (Task [F1])" line after line. The prompt forbids
# them; this is the guard for when the model does it anyway, because a leaked
# marker is unreadable and stripping one is free.
_MARKERS = re.compile(
    r"\s*[\(\[]\s*(?:task|note|record|lead|decision)?\s*\[?[FN]?\d+\]?\s*"
    r"(?:,\s*\"[^\"]*\")?\s*[\)\]]"
    r"|\s*\[unreviewed\]",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = _MARKERS.sub("", text or "")
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _fit(text: str, limit: int) -> str:
    """Cut at a line, then at a sentence, and never mid-word. An answer that
    stops at "forward it to Kanika..." leaves the reader unsure whether the
    list ended or the message did."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for boundary in ("\n", ". "):
        cut = head.rfind(boundary)
        if cut > limit * 0.6:
            head = head[:cut]
            break
    else:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;-") + "\n\n(That is as much as fits here - the rest is on the website.)"


def ask_reply(result: AskResult) -> str:
    text = _fit(_clean(result.answer.text), _MAX_LEN)
    if result.answer.ungrounded_citations:
        text += f"\n\n({result.answer.ungrounded_citations} point(s) couldn't be matched to a transcript - double check those.)"
    return text


def failure_reply(exc: Exception, *, saved: bool) -> str:
    """What to send when processing threw. The daily free-tier quota is the
    common case and is not the sender's fault, so it says so rather than
    looking like the note was rejected. `saved` is True for the paths that
    persist the note to ingestion_failures for a later retry - a lookup has
    nothing to save, so it must not claim otherwise."""
    from app.ingestion.failures import classify_error

    kind = classify_error(exc)
    busy = kind == "api_error" and _looks_busy(exc)

    if kind == "rate_limit":
        if saved:
            return ("Got it, but today's AI limit is used up - your note is saved "
                    "and will be processed once the limit resets.")
        return "Today's AI limit is used up - ask me again once it resets."
    if busy:
        # Not his fault and not ours: the model provider is refusing calls.
        # Saying "try again in a moment" invited exactly that, and the next
        # attempt failed the same way.
        if saved:
            return ("Got your note and kept it. The AI service is overloaded right now, "
                    "so I could not read it yet - it will be processed automatically "
                    "once the service is back. Nothing is lost.")
        return ("The AI service is overloaded right now, so I cannot answer that yet. "
                "Try again in a few minutes - anything you send me to record is still "
                "kept safely in the meantime.")
    if saved:
        return "Got your message but couldn't process it - it's saved, we'll follow up."
    return "Couldn't answer that just now - try again in a moment."


def _looks_busy(exc: Exception) -> bool:
    """A provider capacity error (503/500) rather than a fault in the message."""
    text = str(exc)
    return "503" in text or "UNAVAILABLE" in text or "overloaded" in text.lower()
