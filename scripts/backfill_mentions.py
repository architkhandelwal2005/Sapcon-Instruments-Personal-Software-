# -*- coding: utf-8 -*-
"""Recover the mentions from notes recorded before there was anywhere to put them.

Migration 0023 added meeting_mentions, but the four meetings already on record
resolved their entities and threw the association away. Re-running those notes
through resolution would cost model calls and could land differently; matching
the stored transcripts is free and repeatable.

Deliberately dumber than the resolver, because a backfill has no human reading
a readback afterwards: a record counts only when its full name, or one of its
aliases, appears in the transcript as a whole word. No fuzzy matching, no
sounds-like, no first names. "Shivam Chemical" matches the text that says
Shivam Chemical; it does not match "Shivam Yadav", and "Praj" does not match
inside "Prajapati".

That means it will miss names the transcriber garbled - "Dahij" for Dahej - and
missing one is the right failure here. A wrong mention would make a meeting
surface under a customer it was never about.

Usage:
    backfill_mentions.py            # show what it would record
    backfill_mentions.py --commit
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection

# Shorter than this and a name is more likely to be a word than a record.
MIN_NAME = 4


def _names(canonical: str, aliases, entity_type: str) -> list[str]:
    out = [canonical] + list(aliases or [])
    out = [n.strip() for n in out if n and len(n.strip()) >= MIN_NAME]
    if entity_type == "person":
        # A single-word contact name is not evidence. The book holds a customer
        # called Raghav and a customer called Shivani; so does his own office,
        # and a first name cannot tell them apart. The live resolver already
        # refuses a bare first name for exactly this reason - this is the same
        # rule, applied where there is nobody to read a readback and catch it.
        # Companies keep their single-word names: "Indofil" identifies one.
        out = [n for n in out if " " in n]
    return out


def _spans(transcript: str, name: str) -> list[tuple]:
    # Lookarounds rather than \b: a name may end in punctuation ("L&T Ltd.")
    # and \b would then demand a word character where none can be.
    return [m.span() for m in
            re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", transcript, re.IGNORECASE)]


def _only_inside_a_longer_name(spans: list, others: list) -> bool:
    """Every place this name appeared was part of a longer name that also
    matched - "Pooja" inside "Pooja Pandit". The longer record is the one meant.
    """
    return all(any(o[0] <= s[0] and s[1] <= o[1] and o != s for o in others) for s in spans)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select id, meeting_date, kind, coalesce(raw_transcript,'') from meetings "
                "order by created_at"
            )
            meetings = cur.fetchall()
            cur.execute(
                "select id, canonical_name, aliases, entity_type from entities "
                "where merged_into is null and review_status <> 'rejected'"
            )
            entities = cur.fetchall()
            cur.execute("select meeting_id, entity_id from meeting_mentions")
            already = {(str(m), str(e)) for m, e in cur.fetchall()}
        conn.rollback()

        print(f"{len(meetings)} meetings, {len(entities)} records, "
              f"{len(already)} mentions already recorded\n")

        found: list[tuple] = []
        for meeting_id, meeting_date, kind, transcript in meetings:
            if not transcript:
                continue
            matched = []
            for entity_id, canonical, aliases, entity_type in entities:
                spans = [s for n in _names(canonical, aliases, entity_type)
                         for s in _spans(transcript, n)]
                if spans:
                    matched.append((entity_id, canonical, entity_type, spans))

            every_span = [s for _e, _c, _t, spans in matched for s in spans]
            hits = []
            for entity_id, canonical, entity_type, spans in matched:
                if _only_inside_a_longer_name(spans, every_span):
                    continue
                if (str(meeting_id), str(entity_id)) not in already:
                    hits.append((entity_id, canonical, entity_type))
            print(f"{meeting_date} {kind:<13} {len(hits):>3} named")
            for _eid, canonical, entity_type in sorted(hits, key=lambda h: (h[2], h[1])):
                print(f"      {entity_type:<9} {canonical}")
            found.extend((meeting_id, eid) for eid, _n, _t in hits)
            print()

        print(f"{len(found)} mentions to record")
        if not args.commit:
            print("\nNothing changed. Re-run with --commit.")
            return

        with conn.cursor() as cur:
            cur.executemany(
                "insert into meeting_mentions (meeting_id, entity_id) values (%s,%s)", found)
        conn.commit()
        print("Recorded.")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
