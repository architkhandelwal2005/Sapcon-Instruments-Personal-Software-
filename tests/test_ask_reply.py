"""What an answer looks like on a phone.

Taken from a real reply that went to the user's uncle, which listed every task
twice - once as the record and once as the sentence it was extracted from - and
carried the website's reference markers into the chat.
"""

from dataclasses import dataclass, field

from app.whatsapp.reply import _clean, _fit, ask_reply


@dataclass
class _Answer:
    text: str
    ungrounded_citations: int = 0
    citations: list = field(default_factory=list)


@dataclass
class _Result:
    answer: _Answer


REAL_REPLY = """Here are all the pending tasks and follow-ups:
- Call Priya back to check if the Konkan Dairy opportunity firms up (Task [F1])
- Follow up with Rakesh to get the scope document, owned by Vishal Dixit (Task [F3])
- Send Anil a quotation within two weeks (Note [3], "I need to send Anil a quotation within two weeks.")
- Send documents over [unreviewed] (Task [F9])"""


def test_reference_markers_never_reach_the_phone():
    cleaned = _clean(REAL_REPLY)
    for marker in ("[F1]", "[F3]", "[F9]", "Note [3]", "[unreviewed]", "(Task"):
        assert marker not in cleaned


def test_the_words_around_a_marker_survive_intact():
    cleaned = _clean(REAL_REPLY)
    assert "Call Priya back to check if the Konkan Dairy opportunity firms up" in cleaned
    assert "owned by Vishal Dixit" in cleaned
    assert "Send Anil a quotation within two weeks" in cleaned


def test_a_marker_leaves_no_space_before_the_full_stop():
    assert _clean("Call Priya back (Task [F1]).") == "Call Priya back."


def test_an_answer_that_fits_is_left_alone():
    assert _fit("short answer", 100) == "short answer"


def test_a_long_answer_ends_at_a_line_and_says_so():
    text = "\n".join(f"- item number {i}" for i in range(200))
    out = _fit(text, 300)
    assert len(out) < 420
    assert not out.split("\n\n")[0].endswith("item number")   # never mid-item
    assert "rest is on the website" in out


def test_it_never_cuts_a_word_in_half():
    out = _fit("averyveryverylongsentence with words that keep going on and on", 30)
    assert "sentenc\n" not in out and "wor\n" not in out


def test_an_ungrounded_point_is_still_flagged():
    reply = ask_reply(_Result(_Answer("Two tasks are open (Task [F1]).", ungrounded_citations=1)))
    assert "[F1]" not in reply
    assert "double check" in reply
