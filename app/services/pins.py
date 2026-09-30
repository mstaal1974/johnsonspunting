"""Punter PINs: hashed with PBKDF2, with a short lockout after repeated misses."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.models import Member

MAX_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)
_ITERATIONS = 200_000


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and 4 <= len(pin) <= 8


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _ITERATIONS)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def _matches(pin: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(check.hex(), digest)


def check_pin(member: Member, pin: str, now: datetime | None = None) -> str | None:
    """Returns None when the PIN is right, else a message to show. Caller commits."""
    now = now or datetime.now(timezone.utc)
    if not member.pin_hash:
        return "No PIN has been set for you yet - ask the club admin."
    locked = member.locked_until
    if locked is not None and locked.tzinfo is None:  # SQLite drops the timezone
        locked = locked.replace(tzinfo=timezone.utc)
    if locked and locked > now:
        mins = max(1, int((locked - now).total_seconds() // 60) + 1)
        return f"Too many wrong PINs. Try again in {mins} minute{'s' if mins != 1 else ''}."
    if _matches(pin, member.pin_hash):
        member.failed_logins, member.locked_until = 0, None
        return None
    member.failed_logins = (member.failed_logins or 0) + 1
    if member.failed_logins >= MAX_ATTEMPTS:
        member.failed_logins, member.locked_until = 0, now + LOCKOUT
        return "Too many wrong PINs. Try again in 15 minutes."
    return "Wrong PIN."
