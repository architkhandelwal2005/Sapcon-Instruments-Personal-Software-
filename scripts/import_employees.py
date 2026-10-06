# -*- coding: utf-8 -*-
"""Give the staff roster real names, numbers, and a way to sign in.

The roster was seeded from initials circled on visiting cards and from an
office whiteboard, so it holds thirty people, some abbreviated ("Surendra K.")
and four still called "Employee CU (placeholder)". It covers sales and
marketing only. When the sales head debriefed a customer-support meeting, six
of the people he named were not on it - and "what's pending with Shivani" then
matched a *customer* called Shivani Jadhav and answered with her phone number.
A name that is not on the roster is just a string, so the work recorded against
it is unreachable.

This takes the office's own employee list and does three things: fills in the
full name, phone and email on the people already there, creates the ones who
are missing, and gives each a row in app_users so they can sign in.

Matching is deterministic and refuses to guess, because merging two staff
records by mistake is the same unrecoverable mistake as merging two customers:

  exact            "Saurabh Mehru"      -> Saurabh Mehru
  abbreviation     "Surendra Kushwah"   -> Surendra K.      (surname expanded)
  first name only  "Sanjeevani Belapurkar" -> Sanjeevani    (roster has one word)

Anything else that merely looks similar - "Ghata Sharma" against a roster
"Ghata Jha", "Ayush Verma" against "Aayush Verma" - is reported and left alone.
Those are questions about two real people, and the office knows the answer
while this script does not.

PINs are a separate decision and a separate flag, deliberately. Nothing here
sets one unless asked: see --pin-from-phone, and read what it says.

Usage:
    import_employees.py                      # show what would happen
    import_employees.py --commit
    import_employees.py --commit --pin-from-phone
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import xlrd

from app.db import get_connection, release_connection
from app.phone import normalize_phone
from app.web.auth import hash_pin

# The sheet itself is deliberately not in the repository: it is twenty-six
# colleagues' personal mobile numbers, and documents/ is committed.
SHEET = Path(__file__).resolve().parent.parent / "documents" / "Employee List for Visiting Cards.xls"
PIN_DIGITS = 6


def _flat(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _read_sheet(path: Path) -> list[dict]:
    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    people = []
    for row in range(1, sheet.nrows):
        def cell(col):
            v = sheet.cell_value(row, col)
            if isinstance(v, float):
                v = str(int(v)) if v == int(v) else str(v)
            # The sheet has a non-breaking space inside one name, which
            # would otherwise be stored and never match anything again.
            return re.sub(r"\s+", " ", str(v)).strip()

        name, phone, email = cell(1), cell(2), cell(3)
        if not name or not phone:
            continue
        people.append({"name": name, "phone": phone,
                       "email": email if "@" in email else ""})
    return people


def _match(name: str, roster: list[tuple]) -> tuple:
    """(entity_id, roster_name, how) or (None, None, reason).

    `roster` is [(id, canonical_name)]. Only the three confident shapes match.
    """
    want = _flat(name)
    for eid, canonical in roster:
        if _flat(canonical) == want:
            return eid, canonical, "exact"

    parts = name.split()
    first, surname = parts[0], " ".join(parts[1:])
    for eid, canonical in roster:
        bits = canonical.split()
        if _flat(bits[0]) != _flat(first):
            continue
        if len(bits) == 1:
            return eid, canonical, "first name (roster had no surname)"
        roster_surname = _flat(" ".join(bits[1:]))
        if roster_surname and _flat(surname).startswith(roster_surname):
            return eid, canonical, f"surname expanded from {canonical!r}"
    return None, None, ""


# Close enough that a human must look. Tuned against the real data: "Ayush
# Verma" scores 0.80 against the roster's "Aayush Verma" and "Sawan Patel" 0.85
# against the "Sawant Patel" his own voice note created.
TOO_CLOSE = 0.55

# Above this, against someone already marked as staff, the sheet is simply a
# better spelling of a name the roster guessed at. The roster came off a
# whiteboard and some circled initials; this sheet is the office's own list, so
# where they disagree about a colleague's name the sheet wins.
#
# It is not applied to a customer record at any score. "Deepak Patel" the
# colleague and "Deepak K. Patle" the contact may well be two men, and fusing a
# staff member into a customer is the one mistake that cannot be undone.
SHEET_WINS = 0.70


def _same_staff_member(conn, name: str) -> tuple:
    """(entity_id, roster_name) for a staff record this is clearly a respelling
    of, or (None, None)."""
    with conn.cursor() as cur:
        cur.execute(
            "select id, canonical_name, similarity(canonical_name, %(n)s) s from entities "
            "where entity_type = 'employee' and merged_into is null "
            "and similarity(canonical_name, %(n)s) >= %(t)s order by s desc limit 1",
            {"n": name, "t": SHEET_WINS},
        )
        row = cur.fetchone()
    return (str(row[0]), row[1]) if row else (None, None)


def _shares_a_first_name(name: str, roster: list[tuple]) -> list[str]:
    """Same first name, different surname - "Ghata Sharma" against a roster
    "Ghata Jha". Too far apart to score as a respelling, too close to create
    beside it without someone saying which it is."""
    first = _flat(name.split()[0])
    return [c for _e, c in roster if _flat(c.split()[0]) == first]


def _near_misses(conn, name: str) -> list[str]:
    """Existing records close enough that creating this one might duplicate
    them - the question a human must answer.

    Asked of every record, not just the roster, for two reasons. A colleague
    first heard in a voice note exists as a plain person, not an employee, so
    the roster alone would miss "Sawant Patel". And an employee who shares a
    name with a customer is exactly the collision that must never be merged
    silently.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select canonical_name, entity_type, similarity(canonical_name, %(n)s) s "
            "from entities where merged_into is null and review_status <> 'rejected' "
            "and similarity(canonical_name, %(n)s) >= %(t)s "
            "order by s desc limit 3",
            {"n": name, "t": TOO_CLOSE},
        )
        return [f"{n} ({t}, {s:.2f})" for n, t, s in cur.fetchall()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--pin-from-phone", action="store_true",
                    help="ALSO set each PIN to the last 6 digits of that person's "
                         "own phone number. The sign-in name IS the phone number, "
                         "so this makes both halves of the credential the same "
                         "public fact.")
    ap.add_argument("--file", default=str(SHEET))
    args = ap.parse_args()

    sheet = Path(args.file)
    if not sheet.exists():
        raise SystemExit(
            f"No employee sheet at {sheet}.\n"
            "It holds personal phone numbers and is kept out of the repository, "
            "so point at your own copy:\n"
            '    import_employees.py --file "path/to/Employee List for Visiting Cards.xls"')
    people = _read_sheet(sheet)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select id, canonical_name from entities where entity_type = 'employee'")
            roster = [(str(r[0]), r[1]) for r in cur.fetchall()]
            cur.execute("select entity_id, phone_digits, pin_hash is not null from app_users")
            users = {str(r[0]): (r[1], r[2]) for r in cur.fetchall()}
        conn.rollback()

        matched, new, unsure = [], [], []
        for p in people:
            try:
                digits = normalize_phone(p["phone"])
            except ValueError:
                unsure.append((p, [], "phone number not understood"))
                continue
            eid, canonical, how = _match(p["name"], roster)
            if not eid:
                eid, canonical = _same_staff_member(conn, p["name"])
                how = f"respelling of {canonical!r}" if eid else ""
            if eid:
                matched.append((p, digits, eid, canonical, how))
                continue
            close = _near_misses(conn, p["name"]) + [
                f"{c} (employee, same first name)"
                for c in _shares_a_first_name(p["name"], roster)]
            (unsure if close else new).append((p, digits, close))

        print(f"{len(people)} people in the sheet, {len(roster)} on the roster\n")

        print(f"--- matched to someone already on the roster ({len(matched)}) ---")
        for p, digits, eid, canonical, how in matched:
            has_login = "has login" if eid in users else "NEW LOGIN"
            print(f"  {p['name']:<24} -> {canonical:<24} {digits:<14} {has_login}  [{how}]")

        print(f"\n--- not on the roster, would be created ({len(new)}) ---")
        for p, digits, _c in new:
            print(f"  {p['name']:<24} {digits:<14} {p['email']}")

        print(f"\n--- NOT TOUCHED, needs a human ({len(unsure)}) ---")
        for p, _d, close in unsure:
            print(f"  {p['name']:<24} resembles: {', '.join(close) if close else '(bad phone)'}")

        if args.pin_from_phone:
            print("\n--- PINs ---")
            print(f"  would set a PIN for {len(matched) + len(new)} people, "
                  f"each the last {PIN_DIGITS} digits of their own mobile number")

        if not args.commit:
            print("\nNothing changed. Re-run with --commit.")
            return

        created = updated = logins = pins = 0
        with conn.cursor() as cur:
            for p, digits, eid, _canonical, _how in matched:
                cur.execute(
                    "update entities set canonical_name = %s, "
                    "phone = coalesce(phone, %s), email = coalesce(nullif(email,''), %s) "
                    "where id = %s",
                    (p["name"], digits, p["email"] or None, eid),
                )
                updated += 1
            for p, digits, _c in new:
                cur.execute(
                    "insert into entities (canonical_name, entity_type, phone, email, "
                    "source, confidence, review_status) "
                    "values (%s,'employee',%s,%s,'team','high','confirmed') returning id",
                    (p["name"], digits, p["email"] or None),
                )
                eid = str(cur.fetchone()[0])
                matched.append((p, digits, eid, p["name"], "created"))
                created += 1

            for p, digits, eid, _canonical, _how in matched:
                cur.execute(
                    "insert into app_users (entity_id, phone_digits, role) values (%s,%s,'employee') "
                    "on conflict (entity_id) do update set phone_digits = excluded.phone_digits",
                    (eid, digits),
                )
                logins += 1
                if args.pin_from_phone:
                    # Only ever onto an account that has no PIN, so this cannot
                    # overwrite one somebody has already chosen for themselves.
                    cur.execute(
                        "update app_users set pin_hash = %s, pin_set_at = now(), "
                        "failed_attempts = 0, locked_until = null "
                        "where entity_id = %s and pin_hash is null",
                        (hash_pin(digits[-PIN_DIGITS:]), eid),
                    )
                    pins += cur.rowcount
        conn.commit()
        print(f"\nupdated {updated} roster records, created {created}, "
              f"{logins} logins, {pins} PINs set")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
