"""The names handed to the transcriber before it listens.

Transcription had no idea who this company deals with, so it spelled Indian
proper nouns from sound alone: "Kanika Chadha" came back "Kanika Chanda",
"Parag Milk Foods" came back "Pragmet Foods". The names were in the database
the whole time.
"""

from app.transcription.vocabulary import vocabulary_hint


def test_no_names_means_no_hint():
    assert vocabulary_hint([]) == ""
    assert vocabulary_hint(None) == ""


def test_the_names_are_handed_over():
    hint = vocabulary_hint(["Kanika Chadha", "Parag Milk Foods"])
    assert "Kanika Chadha" in hint and "Parag Milk Foods" in hint


def test_it_forbids_swapping_an_unknown_name_for_a_listed_one():
    """The dangerous failure is not a misspelling, which is visibly wrong. It
    is a confident wrong name, which is not."""
    hint = vocabulary_hint(["Kanika Chadha"]).lower()
    assert "only use a name from that list when the audio genuinely sounds like it" in hint
    assert "never replace it" in hint


def test_a_name_not_on_the_list_is_written_as_heard():
    assert "write what you actually hear" in vocabulary_hint(["Kanika Chadha"])
