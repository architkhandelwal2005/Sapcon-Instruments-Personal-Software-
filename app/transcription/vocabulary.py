"""The names a voice note is likely to contain, for the transcriber to read.

Transcription was being asked to spell Indian proper nouns from sound alone,
with no idea who this company deals with. "Kanika Chadha" came back as "Kanika
Chanda", "Harshil Shah" as "Harshal Shah", and "Parag Milk Foods" as "Pragmet
Foods" - names already sitting in the database, spelled correctly, that the
transcriber was never shown.

A speech model given a list of expected names gets them right far more often.
It costs nothing: the names are already there, and they travel in the prompt we
were already sending.

Two rules shape the list. It is short, because a long one invites the model to
hear a listed name where a different one was said. And staff come first, since
they are said in nearly every note - "tell Vishal", "Sanjeevani will do it" -
while any one customer is said rarely.
"""

from typing import Optional

import psycopg

MAX_STAFF = 40
MAX_CUSTOMERS = 120


def known_names(conn: psycopg.Connection) -> list[str]:
    """Staff, then the people and companies that come up most."""
    return _staff(conn) + _most_mentioned(conn)


def _staff(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "select canonical_name from entities "
            "where entity_type = 'employee' and review_status <> 'rejected' "
            "order by canonical_name limit %s",
            (MAX_STAFF,),
        )
        return [r[0] for r in cur.fetchall()]


def _most_mentioned(conn: psycopg.Connection, limit: int = MAX_CUSTOMERS) -> list[str]:
    """The people and companies he actually talks about, most recent first.

    Ranking by how many rows mention someone does not work here: the visiting
    card import gave roughly seven hundred people one "works at" connection
    each, so they all tie, and the tie is broken alphabetically - which filled
    the list with names nobody has ever said out loud while leaving out Kanika
    Chadha, who had just been named in a voice note.

    Being spoken about is what counts, and recently spoken about counts most: a
    customer discussed last week is likely to come up again this week, while one
    whose card was photographed in March is not.

    One name is never used: one already flagged as a possible duplicate of
    another. That is the system saying it suspects this spelling of being a
    mishearing of a name it already holds - "Harshal Shah" beside the existing
    Harshil Shah - and handing the suspect spelling back to the transcriber
    would teach it the mistake.

    Beyond that the list is not filtered on confidence, and that is deliberate.
    Demanding a human's confirmation emptied it: with a handful of meetings on
    record almost nothing is said twice, so Kanika Chadha, Rakesh Sharma and
    Gujarat Ambuja all fell out along with the junk. A wrong spelling in this
    list is no worse than today, where the transcriber guesses with no list at
    all - the instruction that goes with it forbids substituting a listed name
    for a different one. It also means this list improves every time somebody
    fixes a name in the review queue: correct it once there, and every voice
    note after it is transcribed against the corrected spelling.

    The slots left over go to companies from the contact book. Their names are
    distinctive, they are said far more often than any one contact at them, and
    they come from typed records rather than from audio.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            with said as (
                select r.meeting_id, e.id, e.canonical_name
                from entities e
                join relations r on (r.source_id = e.id or r.target_id = e.id)
                where r.review_status <> 'rejected' and r.meeting_id is not null
                  and e.entity_type in ('person', 'company')

                union

                select m.id, e.id, e.canonical_name
                from entities e join meetings m on m.primary_contact_id = e.id

                union

                -- Named in a task rather than a connection. Kanika Chadha was
                -- missing for exactly that reason, on the same day her name
                -- came back misspelled from a voice note.
                select t.meeting_id, e.id, e.canonical_name
                from entities e
                join tasks t on t.related_entity_id = e.id
                where t.review_status <> 'rejected' and t.meeting_id is not null

                union

                select a.meeting_id, e.id, e.canonical_name
                from entities e join meeting_attendees a on a.employee_id = e.id
            ),
            spoken as (
                select s.canonical_name,
                       count(distinct s.meeting_id) as meetings,
                       max(m.meeting_date) as last_said,
                       bool_or(e.review_status = 'confirmed') as vouched_for,
                       bool_or(e.possible_duplicate_of is not null) as suspect
                from said s
                join entities e on e.id = s.id
                join meetings m on m.id = s.meeting_id
                where e.review_status <> 'rejected' and length(s.canonical_name) > 2
                group by s.canonical_name
            )
            select canonical_name, 0 as tier, last_said
            from spoken
            where not suspect

            union all

            -- Companies from typed records: the contact book, visiting cards,
            -- a person entering one by hand. Their spelling came from paper or
            -- a keyboard rather than from a microphone, so it is the kind
            -- worth priming with.
            select e.canonical_name, 1, null
            from entities e
            where e.entity_type = 'company'
              and e.review_status <> 'rejected'
              and e.possible_duplicate_of is null
              and coalesce(e.source, '') in ('visit_list', 'card', 'diary', 'manual', 'research')
              and length(e.canonical_name) > 3
              and e.canonical_name not in (select canonical_name from spoken)

            order by tier, last_said desc nulls last, 1
            limit %s
            """,
            (limit,),
        )
        return [r[0] for r in cur.fetchall()]


def vocabulary_hint(names: Optional[list[str]]) -> str:
    """The part of the transcription prompt that carries the names.

    The instruction matters as much as the list: a name is only used when the
    audio actually sounds like it. Without that the model will helpfully turn
    an unknown customer into whichever listed name is nearest, which is worse
    than a misspelling - a misspelling is visibly wrong, a confident wrong name
    is not."""
    if not names:
        return ""
    return (
        "\n\nThese are people and companies this business deals with, spelled correctly. "
        "When what you hear matches one of them, use this spelling:\n"
        + ", ".join(names)
        + "\n\nOnly use a name from that list when the audio genuinely sounds like it. "
        "If a name is not on the list, write what you actually hear - never replace it "
        "with the nearest listed name."
    )
