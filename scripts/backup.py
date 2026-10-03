"""Take a copy of everything, and put it back.

Until now the only copy of this data lived in one Supabase project on a free
plan: 1,697 contacts off a spreadsheet, visiting cards and diary pages, the
leads attached to them, and the logins. A deleted project, a wrong migration or
a mistyped `delete` and none of it is recoverable, because there is nowhere to
recover it from.

This writes one file. Every table, every row, the whole public schema, gzipped
JSON. Keep it somewhere that is not Supabase.

Restoring is the half that makes it a backup rather than a souvenir, so it is
here too, and it is deliberately hard to fire by accident: it refuses to touch
a table that already has rows unless told to replace it, and it changes nothing
without --commit.

Two things need care when putting rows back, and both are handled rather than
hoped about:

- Tables go in dependency order, worked out from the foreign keys the database
  itself reports, so a row never arrives before the row it points at.
- A table that points at itself (an entity flagged as a duplicate of another
  entity) cannot be ordered at all. Those columns go in empty and are filled in
  afterwards, once every row exists.

Usage:
    backup.py                           # write backups/sapcon-<date>.json.gz
    backup.py --out somewhere/else.json.gz
    backup.py --restore <file>          # show what it would put back
    backup.py --restore <file> --commit
    backup.py --restore <file> --commit --replace   # overwrite non-empty tables
"""

import argparse
import gzip
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from psycopg.types.json import Jsonb

from app.db import get_connection, release_connection

FORMAT = 1


def _tables(cur) -> list[str]:
    cur.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE' "
        "order by table_name"
    )
    return [r[0] for r in cur.fetchall()]


def _columns(cur, table: str) -> list[tuple[str, str, bool]]:
    """(name, udt_name, may be empty) in the order the table declares them."""
    cur.execute(
        "select column_name, udt_name, is_nullable from information_schema.columns "
        "where table_schema = 'public' and table_name = %s "
        "order by ordinal_position",
        (table,),
    )
    return [(r[0], r[1], r[2] == "YES") for r in cur.fetchall()]


def _primary_keys(cur) -> dict[str, str]:
    """The single column that identifies a row, per table.

    Needed only to fill in the columns that had to go in empty, and a wrong
    guess there would update rows it was never aimed at - so the key is read
    from the database rather than assumed to be the first column, and a table
    keyed on two columns is simply not eligible to have anything deferred.
    """
    cur.execute(
        """
        select tc.table_name, min(kcu.column_name), count(*)
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on kcu.constraint_name = tc.constraint_name
         and kcu.table_schema = tc.table_schema
        where tc.constraint_type = 'PRIMARY KEY' and tc.table_schema = 'public'
        group by tc.table_name
        """
    )
    return {r[0]: r[1] for r in cur.fetchall() if r[2] == 1}


def _foreign_keys(cur) -> list[tuple[str, str, str]]:
    """(table, column, referenced table) for every foreign key in the schema."""
    cur.execute(
        """
        select tc.table_name, kcu.column_name, ccu.table_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on kcu.constraint_name = tc.constraint_name
         and kcu.table_schema = tc.table_schema
        join information_schema.constraint_column_usage ccu
          on ccu.constraint_name = tc.constraint_name
         and ccu.table_schema = tc.table_schema
        where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = 'public'
        """
    )
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def _plan(tables: list[str], keys: list[tuple[str, str, str]],
          nullable: set[tuple[str, str]]) -> tuple[list[str], dict[str, set[str]]]:
    """An order to insert tables in, and the columns that cannot wait for it.

    Most of the schema sorts cleanly: entities before the leads that point at
    them, meetings before their tasks. Two shapes do not sort at all.

    A table pointing at itself - an entity flagged as a duplicate of another
    entity - has no valid order, because some row has to go first.

    And two tables can point at each other. This schema does exactly that: an
    entity records the photographed card it came from, and a photographed card
    records the person who logged it.

    Both are solved the same way. The column goes in empty and is filled once
    every row exists, which is only sound for a column allowed to be empty -
    a required one would be a false repair, so the order is left broken and the
    database is allowed to say so rather than this quietly inventing a null.
    """
    held = defaultdict(set)
    for table, column, target in keys:
        if table == target and table in tables:
            held[table].add(column)

    needs = {t: set() for t in tables}
    edges = defaultdict(list)       # table -> [(column, target)] still ordered
    for table, column, target in keys:
        if table == target or table not in needs or target not in needs:
            continue
        if column in held[table]:
            continue
        needs[table].add(target)
        edges[table].append((column, target))

    out, placed = [], set()
    remaining = sorted(tables)
    while remaining:
        ready = [t for t in remaining if needs[t] <= placed]
        while not ready:
            left = set(remaining)
            breakable = sorted(
                (t, c) for t in remaining for c, target in edges[t]
                if target in left and (t, c) in nullable and c not in held[t]
            )
            if not breakable:
                # Nothing in the cycle may be left empty. Say so by order
                # rather than by a null the schema forbids.
                ready = remaining
                break
            table, column = breakable[0]
            held[table].add(column)
            needs[table] = {tgt for c, tgt in edges[table] if c not in held[table]}
            ready = [t for t in remaining if needs[t] <= placed]
        for t in ready:
            out.append(t)
            placed.add(t)
        remaining = [t for t in remaining if t not in placed]
    return out, {t: cols for t, cols in held.items() if cols}


def _plain(value):
    """JSON cannot hold a uuid, a date or a Decimal; text can, and Postgres
    reads every one of them back from text on the way in."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def backup(out_path: Path) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            tables = _tables(cur)
            data, total = {}, 0
            for table in tables:
                columns = [c for c, _t, _n in _columns(cur, table)]
                cur.execute(f'select {", ".join(columns)} from "{table}"')
                rows = [[_plain(v) for v in row] for row in cur.fetchall()]
                data[table] = {"columns": columns, "rows": rows}
                total += len(rows)
                print(f"  {table:<28} {len(rows):>6}")
        conn.rollback()
    finally:
        release_connection(conn)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": FORMAT, "taken_at": datetime.now().isoformat(), "tables": data}
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    size = out_path.stat().st_size
    print(f"\n{total} rows across {len(data)} tables -> {out_path} ({size / 1024:.0f} KB)")
    print("Keep this somewhere that is not Supabase.")


def restore(path: Path, *, commit: bool, replace: bool) -> None:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("format") != FORMAT:
        raise SystemExit(f"Unrecognised backup format: {payload.get('format')!r}")
    saved = payload["tables"]
    print(f"Backup taken {payload['taken_at']}, {len(saved)} tables\n")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            here = set(_tables(cur))
            keys = _foreign_keys(cur)
            pks = _primary_keys(cur)
            columns_of = {t: _columns(cur, t) for t in here}
            # A column may only be deferred on a table whose rows can be found
            # again afterwards by a single key.
            nullable = {
                (t, c) for t, cols in columns_of.items() if t in pks
                for c, _udt, may_be_empty in cols if may_be_empty
            }
            full_order, deferred_columns = _plan(sorted(here), keys, nullable)
            order = [t for t in full_order if t in saved]
            json_columns = {
                t: {c for c, udt, _n in columns_of[t] if udt in ("json", "jsonb")}
                for t in order
            }

            occupied = []
            for table in order:
                cur.execute(f'select count(*) from "{table}"')
                n = cur.fetchone()[0]
                if n:
                    occupied.append((table, n))

            missing = sorted(set(saved) - here)
            if missing:
                print("In the backup but not in this database (skipped - run the "
                      f"migrations first): {', '.join(missing)}\n")

            for table in order:
                print(f"  {table:<28} {len(saved[table]['rows']):>6} rows")
            if occupied:
                print("\nAlready holding rows:")
                for table, n in occupied:
                    print(f"  {table:<28} {n:>6}")
                if not replace:
                    raise SystemExit(
                        "\nRefusing to restore on top of existing data. Restore into an "
                        "empty database, or pass --replace to clear these tables first."
                    )

            if not commit:
                print("\nNothing changed. Re-run with --commit.")
                conn.rollback()
                return

            if replace:
                for table in reversed(order):
                    cur.execute(f'delete from "{table}"')

            deferred = []       # (table, pk column, pk value, {column: value})
            for table in order:
                columns = saved[table]["columns"]
                rows = saved[table]["rows"]
                if not rows:
                    continue
                later = deferred_columns.get(table, set()) & set(columns)
                as_json = json_columns.get(table, set())
                placeholders = ", ".join(["%s"] * len(columns))
                quoted = ", ".join(f'"{c}"' for c in columns)
                statement = f'insert into "{table}" ({quoted}) values ({placeholders})'
                pk = pks.get(table)

                batch = []
                pk_at = columns.index(pk) if pk in columns else None
                for row in rows:
                    values, held = [], {}
                    for column, value in zip(columns, row):
                        if column in later and value is not None:
                            held[column] = value
                            value = None
                        elif column in as_json and value is not None:
                            value = Jsonb(value)
                        values.append(value)
                    batch.append(values)
                    if held:
                        deferred.append((table, pk, row[pk_at], held))
                # One round trip per statement would mean thousands of them
                # against a database on the other side of the world; psycopg
                # pipelines these instead.
                cur.executemany(statement, batch)
                print(f"  restored {len(rows):>6} into {table}")

            # Every row exists now, so the columns that point within their own
            # table finally have something to point at.
            by_shape = defaultdict(list)
            for table, pk, pk_value, held in deferred:
                by_shape[(table, pk, tuple(held))].append([*held.values(), pk_value])
            for (table, pk, held_columns), rows in by_shape.items():
                sets = ", ".join(f'"{c}" = %s' for c in held_columns)
                cur.executemany(f'update "{table}" set {sets} where "{pk}" = %s', rows)
            if deferred:
                print(f"  linked {len(deferred)} rows back to their own table")

        conn.commit()
        print("\nRestored.")
    finally:
        release_connection(conn)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="where to write the backup")
    parser.add_argument("--restore", default=None, metavar="FILE")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--replace", action="store_true",
                        help="with --restore: clear tables that already hold rows")
    args = parser.parse_args()

    if args.restore:
        restore(Path(args.restore), commit=args.commit, replace=args.replace)
        return

    root = Path(__file__).resolve().parent.parent
    out = Path(args.out) if args.out else root / "backups" / f"sapcon-{date.today()}.json.gz"
    backup(out)


if __name__ == "__main__":
    main()
