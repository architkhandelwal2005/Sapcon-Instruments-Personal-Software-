"""Fixing a name that was heard wrong, from the chat.

"Marmik Sapovadia is the correct spelling. Not Mark Sapadia or Marmik Sapo
Vadi" is the most natural thing to send after reading a readback, and it used
to be filed as a meeting - producing a third record of the same man and a
minute of nothing in the meeting log.

It is also the highest-value correction there is. A name is how every later
mention finds its way to the right record: get it wrong and the same customer
accumulates a record per recording, each holding a fragment of the history.

Merging cannot be cleanly undone, so this never guesses. A wrong name that
matches two records changes nothing and says which two.
"""

from dataclasses import dataclass, field
from typing import Optional

import psycopg

from app.entity_resolution.merge import find_by_name, merge_entities


@dataclass
class CorrectionOutcome:
    status: str                     # applied | not_found | ambiguous | nothing_to_do
    summary: str = ""
    entity_id: Optional[str] = None
    url_path: Optional[str] = None
    candidates: list = field(default_factory=list)


def apply_name_correction(conn: psycopg.Connection, correct: str, wrong: list,
                          *, actor_id: Optional[str] = None) -> CorrectionOutcome:
    """Make `correct` the name, and fold the `wrong` spellings into it."""
    correct = (correct or "").strip()
    if not correct:
        return CorrectionOutcome("not_found", "I did not catch which spelling is the right one.")

    wrong_names = [w.strip() for w in (wrong or []) if w and w.strip().lower() != correct.lower()]

    # Everything the correction names, the right spelling included - it may
    # already exist under the correct name, in which case that is the survivor.
    matches = {}
    for name in [correct] + wrong_names:
        found = find_by_name(conn, name)
        if len(found) > 1 and name in wrong_names:
            return CorrectionOutcome(
                "ambiguous",
                f"\"{name}\" matches more than one record, so I have not merged anything.",
                candidates=[{"id": i, "name": n} for i, n, _ in found],
            )
        if found:
            matches[name] = found[0]

    if not matches:
        return CorrectionOutcome(
            "not_found",
            f"I have no record under \"{correct}\" or the spellings you said were wrong.",
        )

    keep = matches.get(correct)
    renamed_from = None
    if keep is None:
        # Only the wrong spellings exist, so one of them becomes the record and
        # takes the correct name. Renaming beats creating: the history stays.
        keep = matches[wrong_names[0]]
        renamed_from = keep[1]
        with conn.cursor() as cur:
            cur.execute(
                "update entities set canonical_name = %s, "
                "aliases = array(select distinct unnest(coalesce(aliases, '{}') || %s::text[])) "
                "where id = %s",
                (correct, [keep[1]], keep[0]),
            )
        conn.commit()

    keep_id = keep[0]
    merged = []
    for name in wrong_names:
        other = matches.get(name)
        if other is None or other[0] == keep_id:
            continue
        result = merge_entities(conn, keep_id, other[0], actor_id=actor_id)
        merged.append((result.dropped_name, result.rows_moved))

    if not merged and renamed_from is None:
        return CorrectionOutcome(
            "nothing_to_do", f"\"{correct}\" is already the name on that record.",
            entity_id=keep_id, url_path=f"/entities/{keep_id}",
        )

    parts = []
    if renamed_from:
        parts.append(f"Renamed \"{renamed_from}\" to \"{correct}\"")
    for name, rows in merged:
        parts.append(f"folded \"{name}\" into it" + (f" ({rows} record(s) moved)" if rows else ""))
    summary = "; ".join(parts) + ". The old spellings will now resolve here."
    return CorrectionOutcome("applied", summary[0].upper() + summary[1:],
                             entity_id=keep_id, url_path=f"/entities/{keep_id}")
