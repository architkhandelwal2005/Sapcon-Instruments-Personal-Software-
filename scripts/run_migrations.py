"""Apply pending .sql files from migrations/ in filename order.

Avoids a Supabase CLI dependency (and the login it requires) — just needs
DATABASE_URL from the Supabase project's connection settings. Applied
migrations are tracked in a schema_migrations table so re-running is safe.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def main() -> None:
    conn = get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                    filename text primary key,
                    applied_at timestamptz default now()
                )
                """
            )
            cur.execute("select filename from schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            print(f"Applying {path.name}...")
            sql = path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "insert into schema_migrations (filename) values (%s)",
                    (path.name,),
                )
            print(f"Applied {path.name}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
