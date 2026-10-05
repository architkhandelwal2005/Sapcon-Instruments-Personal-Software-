# -*- coding: utf-8 -*-
"""Hindi arrives as speech, and speech is where it has to be settled.

He talks Hinglish - Hindi and English inside one sentence. Asked to transcribe
"in whatever language is spoken", a model writes the Hindi stretches in
Devanagari, and every way this system finds a person reads Latin letters only.
Measured against the real database, a Devanagari name scores 0.000 against its
own record and has an empty metaphone, so it matches nothing, is compared
against nothing, and is therefore created as a brand new person with no flag.

Two defences, and they are deliberately different in kind: the transcript is
asked for in Roman letters, and a name that arrives in another script anyway is
never treated as settled.
"""

from app.entity_resolution.llm_resolve import MatchDecision
from app.entity_resolution.resolve import _beyond_our_matching, resolve_entity
from app.transcription.prompt import transcription_prompt

RAJESH = "राजेश"              # राजेश
RAJESH_SHARMA = "राजेश शर्मा"


class TestTheTranscriptIsAskedForInRomanLetters:
    def test_it_forbids_devanagari(self):
        prompt = transcription_prompt()
        assert "Roman letters" in prompt
        assert "Never use Devanagari" in prompt

    def test_it_keeps_the_hindi_rather_than_translating_it(self):
        """Every extracted fact is checked against a verbatim quote from this
        transcript. Translate it and the quote is no longer what he said."""
        prompt = transcription_prompt()
        assert "do NOT translate" in prompt
        assert "verbatim" in prompt

    def test_it_shows_what_is_wanted_rather_than_only_describing_it(self):
        assert "follow-up karna hai" in transcription_prompt()

    def test_the_names_still_travel_with_it(self):
        """The script rule must not have displaced the vocabulary list - that
        is what stops "Parag Milk Foods" coming back as "Pragmet Foods"."""
        prompt = transcription_prompt(["Rajesh Sharma", "Parag Milk Foods"])
        assert "Parag Milk Foods" in prompt
        assert "Roman letters" in prompt

    def test_no_names_is_still_a_usable_prompt(self):
        assert "Transcribe this audio verbatim" in transcription_prompt(None)


class TestANameWeCannotReadIsNeverSettledQuietly:
    def test_devanagari_is_beyond_the_matchers(self):
        assert _beyond_our_matching(RAJESH_SHARMA)

    def test_a_half_readable_name_counts_too(self):
        """Half a name in Latin can still pull up candidates, and a name we can
        only partly read is one we can only partly judge."""
        assert _beyond_our_matching("Rajesh " + "शर्मा")

    def test_a_careful_transliteration_counts_too(self):
        """Diacritics defeat trigram and metaphone the same way: "Dīkṣita" is
        not going to find "Dixit"."""
        assert _beyond_our_matching("Dīkṣita")

    def test_an_ordinary_name_does_not(self):
        for name in ("Rajesh Sharma", "Parag Milk Foods", "L&T Ltd.", "O'Brien",
                     "Vishal Dixit", "ICE Make Refrigeration Limited"):
            assert not _beyond_our_matching(name), name

    def test_hinglish_written_in_roman_letters_does_not(self):
        """The whole point of the prompt change: this is the shape we want, and
        it must sail straight through."""
        assert not _beyond_our_matching("Rajesh")
        assert not _beyond_our_matching("Sanjeevani")

    def test_digits_and_punctuation_are_not_letters(self):
        assert not _beyond_our_matching("Plant 2 - Unit #4 (50% stake)")

    def test_nothing_is_not_a_problem(self):
        assert not _beyond_our_matching("")
        assert not _beyond_our_matching(None)


class _Cursor:
    """Enough of a cursor for the one path under test: an insert that hands
    back an id. Nothing here reaches a database."""

    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return ("new-entity-id",)


class _Conn:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


def _resolve(monkeypatch, name, *, candidates=()):
    monkeypatch.setattr("app.entity_resolution.resolve.find_candidates",
                        lambda *a, **k: list(candidates))
    conn = _Conn()
    # Decided up front so no model is called; "new" is what the batch resolver
    # returns for a name it was shown no candidates for.
    result = resolve_entity(
        conn, name, "person", "a note about a visit",
        extraction_confidence="high",
        decided=MatchDecision("new", None, "nothing like it on file", "high"),
    )
    return result, conn.cur.statements


class TestWhatHappensToAnUnreadableNameInPractice:
    def test_it_is_created_but_held_for_review(self, monkeypatch):
        """The failure this exists to stop: created clean, live immediately,
        and a second record for a customer already on file."""
        result, _ = _resolve(monkeypatch, RAJESH_SHARMA)
        assert result.outcome == "uncertain_created"
        assert result.review_status == "pending"

    def test_the_row_really_is_written_as_pending(self, monkeypatch):
        _result, statements = _resolve(monkeypatch, RAJESH_SHARMA)
        insert = next(s for s in statements if s[0].startswith("insert into entities"))
        assert "pending" in insert[1]
        assert "auto_confirmed" not in insert[1]

    def test_the_reason_says_why_rather_than_just_that(self, monkeypatch):
        result, _ = _resolve(monkeypatch, RAJESH_SHARMA)
        assert "Latin" in result.reason

    def test_he_sees_it_on_the_readback(self, monkeypatch):
        """uncertain_created is what the readback marks as needing a look, so
        reusing it puts this in front of him with no change there."""
        from app.whatsapp.readback import _entity_lines

        result, _ = _resolve(monkeypatch, RAJESH)
        risky, routine = _entity_lines([result])
        assert risky and not routine
        assert RAJESH in risky[0]

    def test_the_name_is_kept_exactly_as_heard(self, monkeypatch):
        result, _ = _resolve(monkeypatch, RAJESH_SHARMA)
        assert result.canonical_name == RAJESH_SHARMA
        assert result.mentioned_name == RAJESH_SHARMA

    def test_an_ordinary_new_name_is_unaffected(self, monkeypatch):
        """The guard must not quietly send every new contact to review - that
        would bury the ones that genuinely need looking at."""
        result, _ = _resolve(monkeypatch, "Rakesh Agarwal")
        assert result.outcome == "created"
        assert result.review_status == "auto_confirmed"


class TestAHindiInstructionFindsItsTask:
    """The regression that prompted the word list.

    Scoring keeps a match only when it covers 60% of the meaningful words.
    Hindi grammar counted as meaningful and never appears in an English task
    description, so one honest hit read as a partial match and the instruction
    was refused - while the same instruction in English was carried out.
    """

    TASKS = [("t1", "Call Rajesh Sharma about the flow meter quotation",
                    "call rajesh sharma about the flow meter quotation"),
             ("t2", "Send technical specification to Parag Milk Foods",
                    "send technical specification to parag milk foods")]

    def _acts_on(self, target):
        from app.commands.apply import _best_matches, _is_weak, _words

        words = _words(target)
        matches = _best_matches(self.TASKS, words)
        if not matches or _is_weak(self.TASKS, words):
            return None
        return matches[0][0] if len(matches) == 1 else "ambiguous"

    def test_the_hindi_version_now_works(self):
        assert self._acts_on("Rajesh wala task band kar do") == "t1"

    def test_so_does_a_longer_one(self):
        assert self._acts_on("Rajesh ka flow meter wala kaam") == "t1"

    def test_and_the_other_task_is_still_reachable(self):
        assert self._acts_on("Parag Milk Foods ko spec bhej diya") == "t2"

    def test_the_english_version_is_unchanged(self):
        assert self._acts_on("Rajesh task") == "t1"
        assert self._acts_on("the Rajesh one") == "t1"

    def test_the_words_that_name_the_task_still_count(self):
        """Over-inclusive is safe for grammar and fatal for content: if "flow"
        or "meter" were swallowed, two tasks about the same person could no
        longer be told apart."""
        from app.commands.apply import _words

        assert _words("Rajesh ka flow meter wala kaam") == ["rajesh", "flow", "meter"]

    def test_a_name_nobody_has_still_finds_nothing(self):
        assert self._acts_on("Mahesh wala task band kar do") is None


class TestHindiIsNotMistakenForSomebodysName:
    def test_the_two_that_actually_collided(self):
        """Measured against the real contact book: "magar" (but) scored 0.55
        against Amol Magar and "shaniwar" (Saturday) 0.35 against Shubhankar
        Shani. Both would have answered confidently about the wrong person."""
        from app.query.nearby import _candidate_words

        assert _candidate_words("magar woh shaniwar ko aaya tha") == []

    def test_a_hindi_question_offers_only_the_real_name(self):
        from app.query.nearby import _candidate_words

        assert _candidate_words("Rajesh ka kya hua") == ["rajesh"]
        assert _candidate_words("unka quotation bhej diya kya") == []
        assert _candidate_words("is hafte kitna kaam hua") == []

    def test_an_english_question_is_unchanged(self):
        from app.query.nearby import _candidate_words

        assert _candidate_words("whats pending with Mokshil") == ["mokshil"]
        assert _candidate_words("how many calls did we make") == []

    def test_a_hindi_question_about_a_company_still_finds_it(self):
        from app.query.nearby import _candidate_words

        assert _candidate_words("Parag Milk Foods ka kya status hai") == ["parag", "milk", "foods"]
