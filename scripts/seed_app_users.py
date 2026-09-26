"""Give the people already known to the system a login.

Seeds `app_users` from `whatsapp_senders`, which already maps a phone number to
an employee entity and carries the same role vocabulary. Nobody gets a PIN here:
a PIN is set by the person themselves at /enrol with a code the owner issues, so
that knowing someone's phone number is never enough to become them.

Usage:
  seed_app_users.py              # show what would be created
  seed_app_users.py --commit
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.phone import normalize_phone


def main() -> None:
    commit = "--commit" in sys.argv

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select s.phone, s.role, s.entity_id, e.canonical_name
                from whatsapp_senders s join entities e on e.id = s.entity_id
                order by s.role, e.canonical_name
                """
            )
            senders = cur.fetchall()

        created, skipped = [], []
        for phone, role, entity_id, name in senders:
            try:
                digits = normalize_phone(phone)
            except ValueError:
                skipped.append((name, phone, "unparseable phone"))
                continue

            with conn.cursor() as cur:
                cur.execute("select 1 from app_users where entity_id = %s", (entity_id,))
                if cur.fetchone():
                    skipped.append((name, phone, "already has a login"))
                    continue
                if commit:
                    cur.execute(
                        "insert into app_users (entity_id, phone_digits, role) values (%s, %s, %s)",
                        (entity_id, digits, role),
                    )
            created.append((name, digits, role))

        if commit:
            conn.commit()
        else:
            conn.rollback()
    finally:
        release_connection(conn)

    for name, digits, role in created:
        print(f"{'created' if commit else 'would create'}: {name} ({digits}) as {role}")
    for name, phone, why in skipped:
        print(f"skipped: {name} ({phone}) - {why}")
    if not commit:
        print("\nDry run. Re-run with --commit to apply.")
    else:
        print(f"\n{len(created)} login(s) created. Each person still needs a setup code "
              f"from /admin/users before they can choose a PIN.")


if __name__ == "__main__":
    main()
