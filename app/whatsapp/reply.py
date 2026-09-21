"""WhatsApp-sized reply formatters - short, built from counts the pipelines
already return, not a dump of the full read-back (the sender already has the
audio/photo they just sent; the long formatter is for the web meeting page).
"""

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


def ask_reply(result: AskResult) -> str:
    text = result.answer.text
    if len(text) > _MAX_LEN:
        text = text[:_MAX_LEN].rsplit(" ", 1)[0] + "..."
    if result.answer.ungrounded_citations:
        text += f"\n\n({result.answer.ungrounded_citations} point(s) couldn't be matched to a transcript - double check those.)"
    return text
