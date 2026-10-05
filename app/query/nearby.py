"""Who he probably meant, when no name in the question matches one on record.

Name matching in a question is verbatim: the words have to appear as they were
stored. That is unreasonable here, because the stored spelling often came from
a mishearing in the first place. "What's pending with Mokshil" found nothing
and answered honestly that it knew nothing, while Moksha Shah sat in the
database with three records against him.

Trigram similarity, the same measure entity resolution already uses to find
candidates. The difference is what happens next: this never picks silently. A
clear best match is used and named in the reply - "taking that as Moksha Shah"
- so a wrong guess is visible in the answer rather than buried under it. When
two names are equally close, neither is used and both are offered.
"""

from typing import Optional

import psycopg

from app.hinglish import FUNCTION_WORDS

# Below this, "Mokshil" starts matching half the contact book. Chosen so that a
# vowel or two out of place still lands (Mokshil/Moksha, Kanika Chanda/Kanika
# Chadha) while an unrelated name does not.
MIN_SIMILARITY = 0.35

# The roster is thirty people, not seventeen hundred, so a looser bar there
# risks far less and catches far more: "Sanjivni" for Sanjeevani is further off
# than trigram similarity forgives at the general threshold, and staff names
# are the ones said in almost every note.
MIN_SIMILARITY_STAFF = 0.26

# Two candidates this close to each other are not distinguishable by spelling
# alone, so neither is used.
TIE_MARGIN = 0.08

# Ordinary English, which must never be mistaken for somebody's name. "How many
# calls did we make" matched "make" to ICE Make Refrigeration Limited and would
# have answered a question about that company instead. This list only has to
# cover the words that turn up in questions, and being over-inclusive is cheap:
# a real name that lands here simply falls through to the honest "I have
# nothing", which is where it would have gone anyway.
_STOPWORDS = {
    # question words and glue
    "what", "whats", "when", "where", "which", "who", "whos", "whose", "why", "how",
    "with", "about", "from", "that", "this", "there", "their", "them", "they",
    "have", "has", "had", "does", "did", "the", "and", "for", "our", "any", "all",
    "been", "were", "was", "are", "you", "your", "mine", "his", "her", "hers",
    "into", "over", "under", "than", "then", "some", "each", "more", "most",
    # things the CRM holds
    "pending", "left", "open", "closed", "done", "overdue", "task", "tasks",
    "lead", "leads", "meeting", "meetings", "note", "notes", "visit", "visits",
    "quotation", "quote", "brochure", "document", "documents", "report",
    "number", "phone", "email", "details", "contact", "contacts", "customer",
    "company", "client", "team", "target", "status", "summary", "history",
    # verbs he uses asking
    "know", "tell", "give", "show", "brief", "send", "sent", "make", "made",
    "call", "calls", "called", "take", "took", "need", "needs", "want", "wants",
    "said", "say", "says", "told", "work", "works", "working", "follow", "check",
    "update", "updated", "happen", "happened", "going", "come", "came", "get",
    "got", "put", "keep", "find", "found", "list", "anything", "something",
    # time
    "today", "tomorrow", "yesterday", "week", "weeks", "month", "months",
    "year", "years", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "morning", "evening", "next", "last", "time", "back",
    "many", "much", "long", "soon", "here", "also", "just", "only", "still",
    "target", "targets", "order", "orders", "price", "prices", "sales", "site",
    "plant", "project", "projects", "product", "products", "enquiry", "enquiries",
} | FUNCTION_WORDS
# He talks Hinglish, so the glue in a question is as often Hindi as English.
# Only two of them collide with a real contact today - "magar" with Amol Magar,
# "shaniwar" with Shubhankar Shani - but both would have answered confidently
# about the wrong person, which is the failure this list exists to prevent.


# Spelling similarity misses names that sound the same and are written
# differently, which is most of the trouble here: these names reach the
# database through a microphone. "Chanda" and "Chadha" share few trigrams and
# the same metaphone. Entity resolution already scores this way at ingest; a
# question deserves the same.
PHONETIC_BONUS = 0.2


def _with_sound(word: str, rows: list) -> list:
    """Re-score on how the name sounds as well as how it is spelled."""
    try:
        import jellyfish
    except ImportError:
        return sorted(rows, key=lambda r: -r[2])

    code = jellyfish.metaphone(word)
    if not code:
        return sorted(rows, key=lambda r: -r[2])

    out = []
    for entity_id, name, score in rows:
        parts = [name] + name.split()
        if any(jellyfish.metaphone(p) == code for p in parts if len(p) >= 3):
            score = min(1.0, float(score) + PHONETIC_BONUS)
        out.append((entity_id, name, float(score)))
    return sorted(out, key=lambda r: -r[2])


def _candidate_words(question: str) -> list[str]:
    """The words in a question that could be somebody's name."""
    words = []
    for raw in (question or "").replace("?", " ").replace(",", " ").split():
        word = raw.strip(".!'\"").lower()
        if len(word) >= 4 and word.isalpha() and word not in _STOPWORDS:
            words.append(word)
    return words


def nearest_entity(conn: psycopg.Connection, question: str) -> Optional[tuple]:
    """(entity_id, name, the word it matched), or None.

    None covers three cases that must not be told apart by guessing: nothing
    close enough, two things equally close, and no word in the question that
    could be a name at all."""
    words = _candidate_words(question)
    if not words:
        return None

    # Staff first, the same rule the exact-name pass follows: the roster is a
    # closed set of thirty people he names constantly, so "Sanjivni" is far
    # likelier to be Sanjeevani on the team than a customer who happens to
    # share some letters.
    for types in (["employee"], ["person", "company", "employee"]):
        found = _nearest_among(conn, words, types)
        if found is not None:
            return found
    return None


def _nearest_among(conn: psycopg.Connection, words: list, types: list) -> Optional[tuple]:
    best = None
    for word in words:
        with conn.cursor() as cur:
            cur.execute(
                """
                -- Against each part of the name and each alias, as well as the
                -- whole of it. "Marmik" against "Marmik Sapovadia" scores
                -- poorly for the length difference alone, while people say one
                -- part of a name constantly - and an alias is usually the very
                -- spelling that was heard wrong once already, which is exactly
                -- what he is likely to type.
                select e.id, e.canonical_name,
                       greatest(
                           similarity(lower(e.canonical_name), %(w)s),
                           coalesce((select max(similarity(lower(part), %(w)s))
                                     from unnest(string_to_array(e.canonical_name, ' ')) part
                                     where length(part) >= 3), 0),
                           coalesce((select max(similarity(lower(a), %(w)s))
                                     from unnest(coalesce(e.aliases, '{}')) a), 0)
                       ) as score
                from entities e
                where e.review_status <> 'rejected' and e.merged_into is null
                  and e.entity_type = any(%(types)s)
                order by score desc
                limit 8
                """,
                {"w": word, "types": types},
            )
            rows = _with_sound(word, cur.fetchall())

        floor = MIN_SIMILARITY_STAFF if types == ["employee"] else MIN_SIMILARITY
        rows = [r for r in rows if r[2] >= floor][:2]
        if not rows:
            continue
        # Two names equally close to the same word: name both, pick neither.
        if len(rows) > 1 and rows[0][2] - rows[1][2] < TIE_MARGIN:
            continue
        if best is None or rows[0][2] > best[3]:
            best = (str(rows[0][0]), rows[0][1], word, rows[0][2])

    return (best[0], best[1], best[2]) if best else None
