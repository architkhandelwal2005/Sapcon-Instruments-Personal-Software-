"""Phone normalisation and PIN hashing decide who gets in, so they are pinned
here. Both are pure - no database, no model call."""

import pytest

from app.phone import normalize_phone, same_phone
from app.web.auth import MIN_PIN_LENGTH, hash_pin, verify_pin


@pytest.mark.parametrize("written", [
    "9893351932",           # as typed into a login box
    "09893351932",          # as written in a diary
    "+91 98933-51932",      # as printed on a visiting card
    "+919893351932",        # as stored in whatsapp_senders
    "919893351932",         # as WhatsApp reports it
    "0091 98933 51932",     # international prefix
    " 98933 51932 ",        # spaces
])
def test_every_way_of_writing_one_number_gives_one_key(written):
    assert normalize_phone(written) == "919893351932"


def test_two_different_numbers_stay_different():
    assert normalize_phone("9893351932") != normalize_phone("9826080207")


@pytest.mark.parametrize("junk", ["", "   ", "abc", "12345", "-", "9" * 20])
def test_a_number_that_cannot_be_real_is_refused(junk):
    with pytest.raises(ValueError):
        normalize_phone(junk)


def test_same_phone_never_raises_on_junk():
    assert same_phone("+91 98933 51932", "09893351932") is True
    assert same_phone("nonsense", "09893351932") is False


def test_a_pin_verifies_against_its_own_hash():
    stored = hash_pin("481920")
    assert verify_pin("481920", stored) is True


def test_a_wrong_pin_is_refused():
    stored = hash_pin("481920")
    assert verify_pin("481921", stored) is False
    assert verify_pin("", stored) is False


def test_the_same_pin_hashes_differently_every_time():
    # A shared salt would let one cracked PIN reveal everyone using it.
    assert hash_pin("481920") != hash_pin("481920")


@pytest.mark.parametrize("weak", ["1234", "12345", "", "abcdef", "12 34 56"])
def test_a_pin_that_is_too_short_or_not_digits_is_refused(weak):
    with pytest.raises(ValueError):
        hash_pin(weak)


def test_minimum_pin_length_is_six():
    # 4 digits is 10,000 guesses against a public address.
    assert MIN_PIN_LENGTH >= 6


@pytest.mark.parametrize("stored", [None, "", "garbage", "scrypt$bad", "md5$1$2$3$4$5"])
def test_a_damaged_stored_hash_fails_closed(stored):
    assert verify_pin("481920", stored) is False
