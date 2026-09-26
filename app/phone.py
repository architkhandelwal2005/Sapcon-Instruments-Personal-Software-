"""One way to write a phone number.

The same Indian mobile arrives as "+91 98933-51932" from a contact card,
"09893351932" from a diary page, "9893351932" typed into a login box and
"919893351932" from WhatsApp's wa_id. Comparing those as text finds nothing, so
every number is reduced to the same digits before it is stored or matched.
"""

import re

DEFAULT_CC = "91"           # India; the only country this business sells in
_NSN_LENGTH = 10            # Indian national significant number
_MAX_E164_DIGITS = 15       # ITU-T E.164


def normalize_phone(raw: str, *, default_cc: str = DEFAULT_CC) -> str:
    """Digits only, with the country code applied.

    "+91 98933-51932", "09893351932" and "9893351932" all give "919893351932".
    Raises ValueError for anything that cannot be a phone number, so a typo is
    refused at the edge rather than stored as an unmatchable row."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise ValueError("no digits in phone number")

    if len(digits) == _NSN_LENGTH:
        digits = default_cc + digits
    elif digits.startswith("0") and len(digits) == _NSN_LENGTH + 1:
        digits = default_cc + digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]

    if not (len(default_cc) + _NSN_LENGTH <= len(digits) <= _MAX_E164_DIGITS):
        raise ValueError(f"implausible phone number: {len(digits)} digits")
    return digits


def same_phone(a: str, b: str) -> bool:
    """Whether two written forms mean the same number. Never raises - an
    unparseable number simply matches nothing."""
    try:
        return normalize_phone(a) == normalize_phone(b)
    except ValueError:
        return False
