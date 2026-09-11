"""Shared capture pipeline: photo -> vision extraction -> store the photo -> resolve
each item into entities/leads. Mirrors app.ingestion.pipeline's shape (extract ->
resolve -> write, one committed unit) but for images instead of transcripts.

Used by both the web upload fallback (/captures/new) and, later, the WhatsApp photo
webhook.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import psycopg

from app.capture.extract import extract_capture
from app.capture.resolve import ResolvedCaptureItem, resolve_capture_item
from app.capture.storage import upload_photo


@dataclass
class CaptureResult:
    capture_event_id: str
    item_count: int
    auto_confirmed: int
    pending: int
    photo_url: str
    resolved: list[ResolvedCaptureItem] = field(default_factory=list)


def ingest_capture(
    conn: psycopg.Connection,
    image_bytes: bytes,
    mime_type: str,
    capture_type: str,
    captured_date: date,
    logged_by: Optional[str] = None,
) -> CaptureResult:
    if capture_type not in ("card", "diary"):
        raise ValueError(f"capture_type must be 'card' or 'diary', got {capture_type!r}")

    result = extract_capture(image_bytes, mime_type, capture_type)

    capture_event_id = str(uuid.uuid4())
    ext = mime_type.split("/")[-1].replace("jpeg", "jpg")
    photo_url = upload_photo(image_bytes, mime_type, f"{capture_event_id}.{ext}")

    with conn.cursor() as cur:
        cur.execute(
            "insert into capture_events (id, capture_type, photo_url, captured_date, logged_by, raw_extraction) "
            "values (%s,%s,%s,%s,%s,%s)",
            (capture_event_id, capture_type, photo_url, captured_date, logged_by,
             json.dumps(result.model_dump())),
        )

    resolved: list[ResolvedCaptureItem] = []
    for item in result.items:
        resolved.append(resolve_capture_item(conn, item, capture_type, capture_event_id))

    # Count by what the entities actually settled at, not the raw item confidence:
    # a mention that matched an already-trusted entity stays auto_confirmed even
    # from a lower-confidence photo - the match itself, not this one mention, is
    # what's being trusted.
    touched_entity_ids = {i for r in resolved for i in (r.person_id, r.company_id) if i}
    auto = pending = 0
    if touched_entity_ids:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) filter (where review_status = 'pending'), count(*) "
                "from entities where id = any(%s)",
                (list(touched_entity_ids),),
            )
            pending, total = cur.fetchone()
            auto = total - pending

    conn.commit()
    return CaptureResult(
        capture_event_id=capture_event_id, item_count=len(result.items),
        auto_confirmed=auto, pending=pending, photo_url=photo_url, resolved=resolved,
    )
