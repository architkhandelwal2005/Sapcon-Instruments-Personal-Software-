"""Who is using the web app.

The app has been open to anyone who knew its address, while it holds ~700
customer contacts with phone numbers. This closes that, and gives each employee
a login so they can be shown their own work.

Shape of it:
- A person already exists as an `entities` row (`entity_type='employee'`), so a
  credential is keyed to that row rather than inventing a second identity.
- Sign-in is phone number + a 6-digit PIN. Not a WhatsApp one-time code: the
  Meta test number accepts 5 recipients in total, so 29 employees cannot be
  reached until there is a verified production number.
- Sessions live in the database, not in a signed cookie, so signing out and
  revoking someone's access actually work and there is no secret key to manage.
  Only the hash of the cookie value is stored, so a copy of the database cannot
  be used to impersonate anyone.
"""

import hashlib
import hmac
import secrets
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from fastapi import Request

from app.phone import normalize_phone

COOKIE_NAME = "sapcon_session"
# A session ends when someone signs out or their PIN is reset - never on a
# timer. The uncle is on the road and a login that quietly expired would mean
# hunting for a PIN he types a handful of times a year. The column stays, so
# revoking a single session is still one delete.
SESSION_DAYS = 3650
REFRESH_AFTER_HOURS = 24        # don't write to the session row on every request
MIN_PIN_LENGTH = 6              # 4 digits is 10,000 guesses against a public URL
MAX_FAILED = 5
LOCKOUT_MINUTES = 15

ROLES = ("owner", "office", "employee")

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
# Verifying a PIN that does not exist still costs a hash, so response time does
# not tell an attacker which phone numbers are real.
_DUMMY_HASH = None


@dataclass(frozen=True)
class Actor:
    entity_id: str
    name: str
    role: str

    def is_owner(self) -> bool:
        return self.role == "owner"

    def can_review(self) -> bool:
        """Clearing the review queue is the office person's job, and the owner
        can always do anything."""
        return self.role in ("owner", "office")

    def is_employee(self) -> bool:
        return self.role == "employee"


# --------------------------------------------------------------------------
# PINs


def hash_pin(pin: str) -> str:
    """scrypt from the standard library - no new dependency, and deliberately
    slow enough that brute-forcing a 6-digit PIN offline costs real time."""
    _check_pin_shape(pin)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64encode(salt).decode()}${b64encode(dk).decode()}"


def verify_pin(pin: str, stored: Optional[str]) -> bool:
    """Constant-time comparison. A missing or malformed stored value is a
    failure, never an exception."""
    if not stored or not pin:
        return False
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(pin.encode(), salt=b64decode(salt_b64), n=int(n), r=int(r),
                            p=int(p), dklen=len(b64decode(dk_b64)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, b64decode(dk_b64))


def _check_pin_shape(pin: str) -> None:
    if not pin or not pin.isdigit() or len(pin) < MIN_PIN_LENGTH:
        raise ValueError(f"PIN must be at least {MIN_PIN_LENGTH} digits")


def _burn_time() -> None:
    """Spend the same work as a real verification, so an unknown phone number
    and a wrong PIN are indistinguishable from outside."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_pin("0" * MIN_PIN_LENGTH)
    verify_pin("0" * MIN_PIN_LENGTH, _DUMMY_HASH)


# --------------------------------------------------------------------------
# Sessions


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def new_session(conn: psycopg.Connection, entity_id: str, user_agent: str = "") -> str:
    """Returns the raw cookie value; only its hash is stored."""
    raw = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        cur.execute(
            "insert into app_sessions (token_hash, entity_id, expires_at, user_agent) "
            "values (%s, %s, %s, %s)",
            (_token_hash(raw), entity_id, _now() + timedelta(days=SESSION_DAYS), user_agent[:300]),
        )
    conn.commit()
    return raw


def load_actor(conn: psycopg.Connection, raw_token: Optional[str]) -> Optional[Actor]:
    """Who this cookie belongs to, or None. Expired and disabled accounts are
    refused here, so every route gets the check for free."""
    if not raw_token:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            select s.entity_id, e.canonical_name, u.role, s.last_seen_at
            from app_sessions s
            join app_users u on u.entity_id = s.entity_id
            join entities e  on e.id = s.entity_id
            where s.token_hash = %s and s.expires_at > now() and not u.disabled
            """,
            (_token_hash(raw_token),),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        entity_id, name, role, last_seen = row
        stale = last_seen is None or (_now() - last_seen) > timedelta(hours=REFRESH_AFTER_HOURS)
        if stale:
            cur.execute(
                "update app_sessions set last_seen_at = now(), expires_at = %s where token_hash = %s",
                (_now() + timedelta(days=SESSION_DAYS), _token_hash(raw_token)),
            )
    conn.commit() if stale else conn.rollback()
    return Actor(entity_id=str(entity_id), name=name, role=role)


def end_session(conn: psycopg.Connection, raw_token: Optional[str]) -> None:
    if not raw_token:
        return
    with conn.cursor() as cur:
        cur.execute("delete from app_sessions where token_hash = %s", (_token_hash(raw_token),))
    conn.commit()


def end_all_sessions(conn: psycopg.Connection, entity_id: str) -> None:
    """Used when a PIN changes - a new PIN must not leave old logins alive."""
    with conn.cursor() as cur:
        cur.execute("delete from app_sessions where entity_id = %s", (entity_id,))
    conn.commit()


# --------------------------------------------------------------------------
# Signing in


def authenticate(conn: psycopg.Connection, phone: str, pin: str) -> tuple[Optional[Actor], str]:
    """(actor, reason). reason is one of '', 'bad', 'locked', 'no_pin_yet',
    'disabled'. Counts failures and locks the account for a while, because a
    6-digit PIN on a public address is guessable otherwise."""
    try:
        digits = normalize_phone(phone)
    except ValueError:
        _burn_time()
        return None, "bad"

    with conn.cursor() as cur:
        cur.execute(
            """
            select u.entity_id, e.canonical_name, u.role, u.pin_hash, u.disabled,
                   u.failed_attempts, u.locked_until
            from app_users u join entities e on e.id = u.entity_id
            where u.phone_digits = %s
            """,
            (digits,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            _burn_time()
            return None, "bad"

        entity_id, name, role, pin_hash, disabled, failed, locked_until = row
        if disabled:
            conn.rollback()
            return None, "disabled"
        if locked_until is not None and locked_until > _now():
            conn.rollback()
            return None, "locked"
        if not pin_hash:
            conn.rollback()
            return None, "no_pin_yet"

        if not verify_pin(pin, pin_hash):
            failed += 1
            lock = _now() + timedelta(minutes=LOCKOUT_MINUTES) if failed >= MAX_FAILED else None
            cur.execute(
                "update app_users set failed_attempts = %s, locked_until = %s where entity_id = %s",
                (failed, lock, entity_id),
            )
            conn.commit()
            return None, "locked" if lock else "bad"

        cur.execute(
            "update app_users set failed_attempts = 0, locked_until = null, last_login_at = now() "
            "where entity_id = %s",
            (entity_id,),
        )
    conn.commit()
    return Actor(entity_id=str(entity_id), name=name, role=role), ""


# --------------------------------------------------------------------------
# First PIN
#
# There is no channel to send a one-time code on - the Meta test number reaches
# five phones, not a whole team - so a code would have to be read out by the
# owner and typed in by the employee, and in practice that means the owner is
# the help desk for every new joiner and every forgotten PIN.
#
# So an account is claimed instead: the first person to sign in with a number
# the owner has registered chooses the PIN for it. The window is the gap
# between the owner creating the row and the employee's first sign-in, it is
# visible on /admin/users as "not set yet", and it shuts permanently the moment
# a PIN exists. Re-opening it is an owner action (Reset PIN), never automatic.


def claim_account(conn: psycopg.Connection, phone: str, pin: str) -> tuple[Optional[Actor], str]:
    """Set the first PIN for a registered number that has none.

    Refuses an account that already has a PIN, so this can never overwrite a
    working login - a forgotten PIN has to go back through the owner.
    (actor, reason); reason is one of '', 'bad', 'weak_pin', 'disabled',
    'already_set', 'not_registered'."""
    try:
        _check_pin_shape(pin)
    except ValueError:
        return None, "weak_pin"
    try:
        digits = normalize_phone(phone)
    except ValueError:
        return None, "bad"

    with conn.cursor() as cur:
        cur.execute(
            """
            select u.entity_id, e.canonical_name, u.role, u.pin_hash, u.disabled
            from app_users u join entities e on e.id = u.entity_id
            where u.phone_digits = %s
            """,
            (digits,),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            _burn_time()
            # Saying so plainly is the point of this page: a number the owner
            # has not added yet is the one thing the person registering cannot
            # work out for themselves. It reveals nothing the outcome does not
            # already - a registered number visibly proceeds to the PIN step.
            return None, "not_registered"
        entity_id, name, role, pin_hash, disabled = row
        if disabled:
            conn.rollback()
            return None, "disabled"
        if pin_hash:
            conn.rollback()
            return None, "already_set"

        cur.execute(
            "update app_users set pin_hash = %s, pin_set_at = now(), "
            "failed_attempts = 0, locked_until = null where entity_id = %s",
            (hash_pin(pin), entity_id),
        )
    conn.commit()
    return Actor(entity_id=str(entity_id), name=name, role=role), ""


def clear_pin(conn: psycopg.Connection, entity_id: str) -> None:
    """Forget someone's PIN so they choose a new one next time they sign in,
    and sign them out everywhere. This is what "Reset PIN" does - the owner
    never learns, or chooses, anybody's PIN."""
    with conn.cursor() as cur:
        cur.execute(
            "update app_users set pin_hash = null, pin_set_at = null, "
            "failed_attempts = 0, locked_until = null where entity_id = %s",
            (entity_id,),
        )
    conn.commit()
    end_all_sessions(conn, entity_id)


def set_pin(conn: psycopg.Connection, entity_id: str, pin: str) -> None:
    """Also ends every existing session for that person."""
    _check_pin_shape(pin)
    with conn.cursor() as cur:
        cur.execute(
            "update app_users set pin_hash = %s, pin_set_at = now(), failed_attempts = 0, "
            "locked_until = null where entity_id = %s",
            (hash_pin(pin), entity_id),
        )
    conn.commit()
    end_all_sessions(conn, entity_id)


# --------------------------------------------------------------------------


def actor_of(request: Request) -> Actor:
    """The signed-in person, as put there by the middleware. Raises if a route
    was wrongly listed as public - failing loudly beats serving data to nobody
    in particular."""
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise RuntimeError("no actor on the request - is this route listed as public?")
    return actor
