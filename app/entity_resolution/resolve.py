from dataclasses import dataclass
from typing import Literal, Optional

import psycopg

from app.entity_resolution.confirm_queue import confirm_or_choose
from app.entity_resolution.matcher import AUTO_LINK_THRESHOLD, CONFIRM_THRESHOLD, find_candidates

Outcome = Literal["auto_linked", "confirmed", "created", "ambiguous_created"]


@dataclass
class ResolutionResult:
    entity_id: str
    outcome: Outcome
    canonical_name: str
    possible_duplicate_of: Optional[str] = None


def resolve_entity(conn: psycopg.Connection, name: str, entity_type: str, interactive: bool = True) -> ResolutionResult:
    """Resolve a mentioned entity name to an entities.id: auto-link on a
    high-confidence match, prompt via the confirm-queue on a medium-confidence
    match, or create a new entity. Updates aliases when linking under a
    spelling that isn't already the canonical_name or a known alias.

    interactive=False (the CLI's confirm-queue calls input(), which would
    hang forever in a web request with no stdin to read from) skips the
    prompt on a medium-confidence match and creates a new entity instead,
    flagged as "ambiguous_created" with the best candidate it didn't
    auto-link to - safe (never silently mislinks), but the caller should
    surface that flag so a possible duplicate can be merged manually later.
    """
    candidates = find_candidates(conn, name, entity_type)

    if candidates and candidates[0].score >= AUTO_LINK_THRESHOLD:
        top = candidates[0]
        _maybe_add_alias(conn, top.id, name, top.canonical_name, top.aliases)
        return ResolutionResult(entity_id=top.id, outcome="auto_linked", canonical_name=top.canonical_name)

    medium_candidates = [c for c in candidates if c.score >= CONFIRM_THRESHOLD]
    if medium_candidates:
        if interactive:
            chosen_id = confirm_or_choose(name, entity_type, medium_candidates)
            if chosen_id is not None:
                chosen = next(c for c in medium_candidates if c.id == chosen_id)
                _maybe_add_alias(conn, chosen_id, name, chosen.canonical_name, chosen.aliases)
                return ResolutionResult(entity_id=chosen_id, outcome="confirmed", canonical_name=chosen.canonical_name)
        else:
            entity_id = _create_entity(conn, name, entity_type)
            return ResolutionResult(
                entity_id=entity_id,
                outcome="ambiguous_created",
                canonical_name=name,
                possible_duplicate_of=medium_candidates[0].canonical_name,
            )

    entity_id = _create_entity(conn, name, entity_type)
    return ResolutionResult(entity_id=entity_id, outcome="created", canonical_name=name)


def _maybe_add_alias(conn: psycopg.Connection, entity_id: str, name: str, canonical_name: str, aliases: list[str]) -> None:
    if name == canonical_name or name in aliases:
        return
    with conn.cursor() as cur:
        cur.execute(
            "update entities set aliases = array_append(aliases, %s) where id = %s",
            (name, entity_id),
        )


def _create_entity(conn: psycopg.Connection, name: str, entity_type: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "insert into entities (canonical_name, entity_type) values (%s, %s) returning id",
            (name, entity_type),
        )
        (entity_id,) = cur.fetchone()
    return str(entity_id)
