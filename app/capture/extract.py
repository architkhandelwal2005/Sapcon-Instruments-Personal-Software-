"""Vision extraction for photographed visiting cards and diary pages. Parallel to
app.extraction (which is transcript-shaped) - a photo is multi-item (a card sheet
holds ~9-12 cards, a diary page a handful of entries) and has no verbatim quote to
self-check against, so it gets its own small schema and prompt instead of being
forced into the meeting extraction shape.

Same provider gate as everything else: real photographed customer data must not
touch the free Gemini tier - EXTRACTION_PROVIDER must be 'anthropic' before real
photos are processed.
"""

from app.capture.schema import CaptureExtractionResult
from app.llm import complete_json_with_image

_CARD_PROMPT = """You are reading a photo of a sheet of business/visiting cards collected by a \
field salesperson for Sapcon Instruments, an Indian manufacturer selling into process industries \
through consultants, OEMs/integrators, and end users.

Extract ONE item per distinct card visible in the photo. For each card, read only what is \
printed or clearly handwritten on it:
- person_name: the person's name as printed.
- title: their designation/department, if printed.
- company_name: the company name as printed.
- phone, email: as printed. If several numbers are printed, take the first mobile number.
- allotted_initials: a short handwritten code (usually 1-4 letters) circled or written near the \
card - this marks which of the salesperson's team it has been allotted to. Read it exactly as \
written. Leave null if no such mark is visible on or near that card.
- note: any other handwritten annotation near the card (e.g. "send brochure", "call next week"). \
Leave null if none.

CONFIDENCE per item: "high" only for a clean, fully legible printed card with an unambiguous \
circled code. "medium" if any field is partly obscured, glare, or the code is ambiguous. "low" if \
you are guessing at any field. Never invent a value that is not actually visible - leave it null \
instead.

Return JSON: {"items": [{"person_name": ..., "title": ..., "company_name": ..., "phone": ..., \
"email": ..., "allotted_initials": ..., "note": ..., "confidence": "high"|"medium"|"low"}, ...]}"""

_DIARY_PROMPT = """You are reading a photo of a page from a field salesperson's handwritten diary \
for Sapcon Instruments, an Indian manufacturer selling into process industries. The page has \
handwritten notes, leads, and contacts - each entry usually bracketed or circled with a short \
handwritten code marking which team member it is allotted to.

Extract ONE item per distinct entry on the page:
- person_name, title, company_name, phone, email: whatever is actually written for that entry. \
Leave a field null if it was not written.
- allotted_initials: the short handwritten code (usually 1-4 letters) circled or bracketed with \
this entry. Read it exactly as written; null if none visible.
- note: the substance of what was written for this entry (the lead, the ask, the context) - this \
is handwritten free text, summarise it in a short clean sentence rather than transcribing every \
stroke, but do not invent detail that is not there.

CONFIDENCE: handwriting is never "high" confidence even when clearly legible - cap every item at \
"medium" unless genuinely unreadable, in which case "low". Never invent a value not actually \
legible - leave it null instead.

Return JSON: {"items": [{"person_name": ..., "title": ..., "company_name": ..., "phone": ..., \
"email": ..., "allotted_initials": ..., "note": ..., "confidence": "medium"|"low"}, ...]}"""


def extract_capture(image_bytes: bytes, mime_type: str, capture_type: str) -> CaptureExtractionResult:
    prompt = _CARD_PROMPT if capture_type == "card" else _DIARY_PROMPT
    raw = complete_json_with_image(
        prompt, "Extract every item from this photo.", image_bytes, mime_type, max_tokens=4096
    )
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    result = CaptureExtractionResult(items=items)
    if capture_type == "diary":
        # Belt and braces on the confidence cap - don't trust the model alone.
        for item in result.items:
            if item.confidence == "high":
                item.confidence = "medium"
    return result
