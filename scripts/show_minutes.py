"""Print the stored minutes for a meeting, by meeting id."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: show_minutes.py <meeting_id>")
    meeting_id = sys.argv[1]

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("select minutes from meetings where id = %s", (meeting_id,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"No meeting found with id {meeting_id!r}")
        print(row[0] or "(minutes not generated yet)")
    conn.close()


if __name__ == "__main__":
    main()
