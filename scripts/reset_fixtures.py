"""Wipe all data tables (leaving schema_migrations) so the DB starts clean.

Used when synthetic/fixture data needs clearing before a schema change or a
real import. Not destructive of anything real - by the time this is run the
DB only holds test fixtures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection

TABLES = ["entities", "meetings", "relations", "tasks", "entity_review_queue", "ingestion_failures"]


def main() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"truncate table {', '.join(TABLES)} cascade")
            conn.commit()
            for t in TABLES:
                cur.execute(f"select count(*) from {t}")
                print(f"{t}: {cur.fetchone()[0]}")
    finally:
        release_connection(conn)
    print("Done.")


if __name__ == "__main__":
    main()
