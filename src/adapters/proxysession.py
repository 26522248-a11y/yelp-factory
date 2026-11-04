"""Per-account sticky proxy sessions (Oxylabs mobile style usernames).

The configured raw proxy can pin a session id that expires (``sessid-...-sesstime-10``).
Oxylabs answers 502 once it dies, so each account gets its own deterministic session id and a
30 minute sticky window, avoiding both dead sessions and IP sharing between accounts.
"""

from __future__ import annotations

import hashlib
import re

SESSION_RE = re.compile(r"sessid-[^-]+(?:-sesstime-\d+)?")


def session_id_for(account_id: str) -> str:
    digest = hashlib.sha256(account_id.encode()).hexdigest()
    return str(int(digest[:10], 16) % 10_000_000_000).zfill(10)


def rotate_session(raw: str, account_id: str, *, sticky_minutes: int = 30) -> str:
    if "sessid-" not in raw:
        return raw
    replacement = f"sessid-{session_id_for(account_id)}-sesstime-{sticky_minutes}"
    return SESSION_RE.sub(replacement, raw)


def normalize(raw: str) -> str:
    """Strip an expired sticky window so the provider hands out a fresh IP."""
    return SESSION_RE.sub("", raw).replace("--", "-")
