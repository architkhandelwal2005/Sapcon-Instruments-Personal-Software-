"""Join two records that turned out to be one person or one company.

The system could already say "these two might be the same" - thirty-six such
flags are open - but nothing could act on it. So "Mark Sapadia", "Marmik Sapo
Vadi" and "Marmik Sapovadia" piled up as three different people, and telling
the bot the correct spelling on WhatsApp could only add a fourth.

Nothing is destroyed. Every row that pointed at the record being merged away is
repointed at the survivor, the wrong spelling is kept as an alias so the same
mishearing resolves correctly next time, and the merged row itself stays behind
marked with where its history went. Same rule as a rejected review item or a
dropped lead: hidden, not deleted.

The columns to repoint are read from the database rather than listed here. A
list would be right on the day it was written and quietly wrong the first time
a table gained a reference to an entity - and a missed column means a task or a
lead pointing at a record nobody can see any more.
"""

from dataclasses import dataclass, field
from typing import Optional

import psycopg

# Repointing these would move the wrong thing: somebody's login, the phone
# number the webhook matches on, their open sessions. Those belong to whoever
# holds the account; a merge is about the customer record, not the account.
SKIP = {
    ("app_users", "entity_id"),
    ("app_sessions", "entity_id"),
    ("whatsapp_senders", "entity_id"),
}


@dataclass
class MergeResult:
    kept_id: str
    kept_name: str
    dropped_name: str
    moved: dict = field(default_factory=dict)

    @property
    def rows_moved(self) -> int:
        return sum(self.moved.values())


def _referencing_columns(conn: psycopg.Connection) -> list:
    """Every (table, column) that points at entities(id), asked of the schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select tc.table_name, kcu.column_name
            from information_schema.table_constraints tc
            join information_schema.key_column_usage kcu
                 on kcu.constraint_name = tc.constraint_name
                and kcu.table_schema = tc.table_schema
            join information_schema.constraint_column_usage ccu
                 on ccu.constraint_name = tc.constraint_name
                and ccu.table_schema = tc.table_schema
            where tc.constraint_type = 'FOREIGN KEY'
              and tc.table_schema = 'public'
              and ccu.table_name = 'entities'
              and ccu.column_name = 'id'
            order by tc.table_name, kcu.column_name
            """
        )
        return [(t, c) for t, c in cur.fetchall() if (t, c) not in SKIP]


def merge_entities(conn: psycopg.Connection, keep_id: str, drop_id: str,
                   *, actor_id: Optional[str] = None) -> MergeResult:
    """Move everything from `drop_id` onto `keep_id`. Commits on success."""
    if keep_id == drop_id:
        raise ValueError("cannot merge a record into itself")

    with conn.cursor() as cur:
        cur.execute(
            "select id, canonical_name, entity_type, phone, email, title, region, notes, aliases "
            "from entities where id in (%s, %s)",
            (keep_id, drop_id),
        )
        rows = {str(r[0]): r for r in cur.fetchall()}
    if keep_id not in rows or drop_id not in rows:
        conn.rollback()
        raise ValueError("one of those records does not exist")

    keep, drop = rows[keep_id], rows[drop_id]
    result = MergeResult(kept_id=keep_id, kept_name=keep[1], dropped_name=drop[1])

    with conn.cursor() as cur:
        for table, column in _referencing_columns(conn):
            cur.execute(
                f"update {table} set {column} = %s where {column} = %s",  # names come from the schema
                (keep_id, drop_id),
            )
            if cur.rowcount:
                result.moved[f"{table}.{column}"] = cur.rowcount

        # A connection from a record to itself says nothing, and would read on
        # the profile as "Marmik Sapovadia works with Marmik Sapovadia".
        cur.execute("delete from relations where source_id = target_id returning id")
        selfies = len(cur.fetchall())
        if selfies:
            result.moved["relations (self-referring, removed)"] = selfies

        # The wrong spelling becomes an alias, so the same mishearing lands on
        # this record next time instead of making another new one.
        aliases = list(keep[8] or [])
        for name in [drop[1]] + list(drop[8] or []):
            if name and name != keep[1] and name not in aliases:
                aliases.append(name)

        # Fill anything the survivor was missing: a detail is worth keeping
        # wherever it happened to be written down.
        fills = {}
        for idx, column in ((3, "phone"), (4, "email"), (5, "title"), (6, "region")):
            if not keep[idx] and drop[idx]:
                fills[column] = drop[idx]
        notes = "\n".join(n for n in (keep[7], drop[7]) if n)

        sets = ", ".join(f"{c} = %({c})s" for c in fills)
        params = {"aliases": aliases, "notes": notes or None, "id": keep_id}
        params.update(fills)
        cur.execute(
            "update entities set aliases = %(aliases)s, notes = %(notes)s"
            + (", " + sets if sets else "")
            + " where id = %(id)s",
            params,
        )

        cur.execute(
            "update entities set merged_into = %s, review_status = 'rejected' where id = %s",
            (keep_id, drop_id),
        )
        # The flag that suggested this is answered now, whichever way round it
        # happened to be recorded.
        cur.execute(
            "delete from entity_review_queue "
            "where entity_id in (%s, %s) and possible_duplicate_of in (%s, %s)",
            (keep_id, drop_id, keep_id, drop_id),
        )
        cur.execute(
            "update entities set possible_duplicate_of = null "
            "where possible_duplicate_of = %s or id = %s",
            (drop_id, keep_id),
        )
        _record(cur, keep_id, drop_id, result, actor_id)
    conn.commit()
    return result


def _record(cur, keep_id: str, drop_id: str, result: MergeResult,
            actor_id: Optional[str]) -> None:
    """Append-only note of who joined what, so a merge can be questioned later."""
    try:
        cur.execute(
            "insert into review_decisions (kind, item_id, decision, decided_by, note) "
            "values ('entity', %s, 'merged', %s, %s)",
            (drop_id, actor_id,
             f"merged into {keep_id} ({result.kept_name}); {result.rows_moved} row(s) moved"),
        )
    except Exception:
        pass    # worth having, never worth failing the merge for


def find_by_name(conn: psycopg.Connection, name: str) -> list:
    """Records whose name or alias matches these words, best first.

    Used when somebody names a record in words rather than pointing at one -
    "not Mark Sapadia" - so an exact hit must outrank a partial one, or a
    correction lands on the wrong record."""
    text = (name or "").strip()
    if len(text) < 3:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, canonical_name, entity_type
            from entities
            where merged_into is null and review_status <> 'rejected'
              and (lower(canonical_name) = lower(%(n)s)
                   or canonical_name ilike %(like)s
                   or exists (select 1 from unnest(coalesce(aliases, '{}')) a
                              where lower(a) = lower(%(n)s)))
            order by (lower(canonical_name) = lower(%(n)s)) desc, length(canonical_name)
            limit 10
            """,
            {"n": text, "like": "%" + text + "%"},
        )
        return [(str(r[0]), r[1], r[2]) for r in cur.fetchall()]
