"""What the transcriber is told.

Mirrors app/extraction/prompt.py: the words sent to a model belong with the
part of the system that cares what comes back, not in the generic LLM seam.

The script rule is the whole reason this file exists. He speaks Hinglish -
Hindi and English mixed inside one sentence - and asked to transcribe "in
whatever language is spoken", a model will write the Hindi stretches in
Devanagari. That is faithful, and it quietly breaks the thing everything else
depends on.

Every way this system finds a person is Latin-script by construction: trigram
similarity over the spelling, and metaphone over the sound. A Devanagari name
does not score badly against its own record - it scores zero, so no candidates
are found at all. And a name with no candidates is not flagged as a possible
duplicate, because there is nothing to flag it against. It is simply created.
Measured against the real database: similarity('<devanagari>', 'Rajesh Sharma')
is 0.000 and metaphone of the same name is the empty string.

So a Hindi-heavy note would build a second contact book beside the real one,
one new person per mention, with nothing anywhere saying so.

The fix is to keep his words and change only the alphabet they are written in.
Translating instead would be worse: every extracted fact is checked against a
verbatim quote from this transcript, and a translated transcript is no longer
what he said.
"""

from app.transcription.vocabulary import vocabulary_hint

_BASE = (
    "Transcribe this audio verbatim. "
    "Return only the transcript text - no commentary, no timestamps, no speaker labels."
)

# Named so the reason survives: Roman letters are not a preference, they are
# what the name matching can read.
_SCRIPT_RULE = (
    "\n\nThe speaker mixes Hindi and English, often inside one sentence. Keep every word "
    "exactly as it was said - do NOT translate the Hindi into English - but write the whole "
    "transcript in Roman letters. Never use Devanagari or any other script.\n"
    'Write: "kal Rajesh ko follow-up karna hai, quotation bhej denge"\n'
    'Not:   "कल राजेश को follow-up करना है"'
)


def transcription_prompt(names: "list[str] | None" = None) -> str:
    return _BASE + _SCRIPT_RULE + vocabulary_hint(names)
