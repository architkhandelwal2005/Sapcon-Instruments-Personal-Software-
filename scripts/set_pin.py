"""Set someone's PIN directly, from a machine with database access.

This exists for the first account: the owner cannot issue himself a setup code
through a page he cannot sign in to yet. Everyone else should go through
/admin/users and /enrol, so that a PIN is only ever chosen by its owner.

The PIN is read from a prompt rather than an argument, so it does not land in
shell history or in the process list.

Usage: set_pin.py <phone>
"""

import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.phone import normalize_phone
from app.web.auth import MIN_PIN_LENGTH, set_pin


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: set_pin.py <phone>")
    digits = normalize_phone(sys.argv[1])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select u.entity_id, e.canonical_name, u.role from app_users u "
                "join entities e on e.id = u.entity_id where u.phone_digits = %s",
                (digits,),
            )
            row = cur.fetchone()
        conn.rollback()
        if row is None:
            raise SystemExit(f"No login for {digits}. Add one at /admin/users first.")
        entity_id, name, role = row

        pin = getpass(f"New PIN for {name} ({role}), at least {MIN_PIN_LENGTH} digits: ")
        if pin != getpass("Again: "):
            raise SystemExit("PINs did not match.")
        set_pin(conn, str(entity_id), pin)
    finally:
        release_connection(conn)

    print(f"PIN set for {name}. Any existing sessions were signed out.")


if __name__ == "__main__":
    main()
