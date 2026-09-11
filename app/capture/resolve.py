"""Turn one extracted card/diary item into entities + (optionally) a lead. Reuses
the exact same resolve_entity() everything else goes through - a person mentioned on
a card and the same person mentioned in a voice note land on the same entity row,
no second resolution codepath.

Unmatched allotment initials never guess an employee - the lead is created
unassigned and the office boy allots it by hand in review.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import psycopg

from app.capture.schema import ExtractedCaptureItem
from app.entity_resolution.resolve import resolve_entity


@dataclass
class ResolvedCaptureItem:
    person_id: Optional[str]
    company_id: Optional[str]
    lead_id: Optional[str]
    assigned_to: Optional[str]


def _match_employee(conn: psycopg.Connection, initials: Optional[str]) -> Optional[str]:
    if not initials or not initials.strip():
        return None
    with conn.cursor() as cur:
        cur.execute(
            "select id from entities where entity_type = 'employee' "
            "and exists (select 1 from unnest(aliases) a where upper(a) = upper(%s))",
            (initials.strip(),),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def resolve_capture_item(
    conn: psycopg.Connection,
    item: ExtractedCaptureItem,
    capture_type: str,
    capture_event_id: str,
) -> ResolvedCaptureItem:
    context = f"From a photographed {capture_type}: " + ", ".join(
        v for v in (item.person_name, item.title, item.company_name, item.note) if v
    )

    company_id = None
    if item.company_name:
        r = resolve_entity(
            conn, item.company_name, "company", context,
            extraction_confidence=item.confidence,
            source=capture_type, capture_event_id=capture_event_id,
        )
        company_id = r.entity_id

    person_id = None
    if item.person_name:
        r = resolve_entity(
            conn, item.person_name, "person", context,
            extraction_confidence=item.confidence,
            attrs={"title": item.title, "phone": item.phone, "email": item.email},
            source=capture_type, capture_event_id=capture_event_id,
        )
        person_id = r.entity_id

    if person_id and company_id:
        status = "auto_confirmed" if item.confidence == "high" else "pending"
        with conn.cursor() as cur:
            cur.execute(
                "insert into relations (source_id, target_id, role_tag, description, provenance, "
                "recorded_at, confidence, review_status) "
                "values (%s,%s,'employer','works at','direct',%s,%s,%s)",
                (person_id, company_id, date.today(), item.confidence, status),
            )

    lead_entity_id = person_id or company_id
    if lead_entity_id is None:
        return ResolvedCaptureItem(person_id=None, company_id=None, lead_id=None, assigned_to=None)

    assigned_to = _match_employee(conn, item.allotted_initials)
    with conn.cursor() as cur:
        cur.execute(
            "insert into leads (entity_id, assigned_to, source, notes, capture_event_id) "
            "values (%s,%s,%s,%s,%s) returning id",
            (lead_entity_id, assigned_to, capture_type, item.note, capture_event_id),
        )
        (lead_id,) = cur.fetchone()

    return ResolvedCaptureItem(
        person_id=person_id, company_id=company_id, lead_id=str(lead_id), assigned_to=assigned_to
    )
