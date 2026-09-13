"""Seed placeholder employee entities from the initials actually visible on the
uncle's visit-card and diary photos, so card/diary allotment has something real to
resolve against before the real employee list arrives.

Placeholders only - `canonical_name` is meant to be overwritten once real names are
known: `update entities set canonical_name = 'Real Name' where id = '<id>'`. No
re-import needed, no schema change.

Re-run-safe: skips any initials that already exist as an employee entity (matched on
the alias, case-insensitive).

Dry-run by default. --commit writes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection

# Initials seen on the sample visit-card and diary photos. Extend this list as more
# photos surface initials not seen yet - re-running only adds what's missing.
PLACEHOLDER_INITIALS = [
    "EJ", "VD", "VT", "AN", "PP", "BD", "M", "SK", "ML", "CU", "SDM",
]

# The uncle himself is not on the marketing team but does log meetings and change
# lead status - needs an entity row too so logged_by/status_changed_by can reference
# him like anyone else. entity_type stays 'employee' (no separate type for one row);
# 'OWNER' alias is how the rest of the app picks him out.
OWNER = {"initials": "OWNER", "name": "Uncle (owner) - placeholder"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write to the DB (default: dry-run)")
    args = ap.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select unnest(aliases) from entities where entity_type = 'employee'"
            )
            existing = {a.upper() for (a,) in cur.fetchall() if a}

        to_create = [i for i in PLACEHOLDER_INITIALS if i.upper() not in existing]
        owner_missing = OWNER["initials"].upper() not in existing
        print(f"{len(to_create)} new placeholder employee(s) to create: {to_create}")
        print(f"{len(PLACEHOLDER_INITIALS) - len(to_create)} already exist, skipped.")
        print(f"Owner row: {'to create' if owner_missing else 'already exists, skipped'}.")

        if not args.commit:
            print("\nDRY RUN - nothing written. Re-run with --commit.")
            return

        with conn.cursor() as cur:
            for initials in to_create:
                cur.execute(
                    "insert into entities (canonical_name, entity_type, aliases, source, review_status) "
                    "values (%s, 'employee', %s, 'team', 'confirmed')",
                    (f"Employee {initials} (placeholder)", [initials]),
                )
            if owner_missing:
                cur.execute(
                    "insert into entities (canonical_name, entity_type, aliases, source, review_status) "
                    "values (%s, 'employee', %s, 'team', 'confirmed')",
                    (OWNER["name"], [OWNER["initials"]]),
                )
        conn.commit()
        print(f"\nCommitted {len(to_create) + (1 if owner_missing else 0)} row(s).")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
