from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

import psycopg

from app.entity_resolution.llm_resolve import decide_match
from app.entity_resolution.matcher import find_candidates

Outcome = Literal["linked", "created", "uncertain_created"]

ENRICHABLE = ("title", "phone", "email", "region")


@dataclass
class ResolutionResult:
    entity_id: str
    outcome: Outcome
    canonical_name: str
    review_status: str
    reason: str = ""
    possible_duplicate_of: Optional[str] = None
    conflicts: list[str] = field(default_factory=list)


def resolve_entity(
    conn: psycopg.Connection,
    name: str,
    entity_type: str,
    context: str,
    *,
    extraction_confidence: str = "medium",
    attrs: Optional[dict] = None,
) -> ResolutionResult:
    """Resolve a mentioned name to an entities.id via LLM match decision.
    - confident match  -> link, add spelling as alias, fill any missing attrs
    - unsure / medium  -> new entity + possible_duplicate_of + review queue
    - clearly new      -> new entity; auto_confirmed only if extraction and
                          match were both high-confidence, else pending
    Never silently merges.
    """
    attrs = {k: (attrs or {}).get(k) for k in ENRICHABLE}
    candidates = find_candidates(conn, name, entity_type)
    d = decide_match(name, entity_type, context, candidates)

    if d.decision == "match" and d.confidence == "high" and d.match_id:
        top = next(c for c in candidates if c.id == d.match_id)
        _maybe_add_alias(conn, top.id, name, top.canonical_name, top.aliases)
        conflicts = _enrich(conn, top.id, attrs)
        return ResolutionResult(
            entity_id=top.id, outcome="linked", canonical_name=top.canonical_name,
            review_status="auto_confirmed", reason=d.reason, conflicts=conflicts,
        )

    if d.decision in ("match", "uncertain") and candidates:
        dup_id = d.match_id or candidates[0].id
        dup_name = next((c.canonical_name for c in candidates if c.id == dup_id), candidates[0].canonical_name)
        entity_id = _create_entity(conn, name, entity_type, attrs, extraction_confidence, "pending", dup_id)
        _flag_for_review(conn, entity_id, dup_id, name, entity_type)
        return ResolutionResult(
            entity_id=entity_id, outcome="uncertain_created", canonical_name=name,
            review_status="pending", reason=d.reason, possible_duplicate_of=dup_name,
        )

    review_status = "auto_confirmed" if extraction_confidence == "high" and d.confidence == "high" else "pending"
    entity_id = _create_entity(conn, name, entity_type, attrs, extraction_confidence, review_status, None)
    return ResolutionResult(
        entity_id=entity_id, outcome="created", canonical_name=name,
        review_status=review_status, reason=d.reason,
    )


def _maybe_add_alias(conn, entity_id, name, canonical_name, aliases) -> None:
    if name == canonical_name or name in aliases:
        return
    with conn.cursor() as cur:
        cur.execute("update entities set aliases = array_append(aliases, %s) where id = %s", (name, entity_id))


def _enrich(conn, entity_id: str, attrs: dict) -> list[str]:
    """Fill only missing attributes. A value that conflicts with an existing
    non-null one is NOT overwritten - it's appended to notes for review."""
    with conn.cursor() as cur:
        cur.execute(f"select {', '.join(ENRICHABLE)} from entities where id = %s", (entity_id,))
        current = dict(zip(ENRICHABLE, cur.fetchone()))
        sets, params, conflicts = [], [], []
        for k, new_val in attrs.items():
            if not new_val:
                continue
            if current[k] is None:
                sets.append(f"{k} = %s")
                params.append(new_val)
            elif str(current[k]).strip().lower() != str(new_val).strip().lower():
                conflicts.append(f"{date.today().isoformat()}: note said {k}={new_val!r}, kept existing {current[k]!r}")
        if sets:
            params.append(entity_id)
            cur.execute(f"update entities set {', '.join(sets)} where id = %s", params)
        if conflicts:
            cur.execute(
                "update entities set notes = concat_ws(chr(10), notes, %s) where id = %s",
                (chr(10).join(conflicts), entity_id),
            )
    return conflicts


def _flag_for_review(conn, entity_id, possible_duplicate_id, mentioned_name, entity_type) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into entity_review_queue (entity_id, possible_duplicate_of, mentioned_name, entity_type) "
            "values (%s, %s, %s, %s)",
            (entity_id, possible_duplicate_id, mentioned_name, entity_type),
        )


def _create_entity(conn, name, entity_type, attrs, confidence, review_status, possible_duplicate_of) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "insert into entities (canonical_name, entity_type, title, phone, email, region, "
            "confidence, review_status, possible_duplicate_of, source) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'meeting') returning id",
            (name, entity_type, attrs.get("title"), attrs.get("phone"), attrs.get("email"),
             attrs.get("region"), confidence, review_status, possible_duplicate_of),
        )
        (entity_id,) = cur.fetchone()
    return str(entity_id)
