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
    """Give every account its own sticky exit IP.

    Works for usernames that already carry ``sessid`` (replace) and for plain Oxylabs
    usernames from Telegram exports (append the sticky parameters).
    """
    replacement = f"sessid-{session_id_for(account_id)}-sesstime-{sticky_minutes}"
    if "sessid-" in raw:
        return SESSION_RE.sub(replacement, raw)
    parts = raw.split(":", 3)
    if len(parts) != 4 or not parts[2].startswith("customer-"):
        return raw
    host, port, username, password = parts
    return f"{host}:{port}:{username}-{replacement}:{password}"


def normalize(raw: str) -> str:
    """Strip an expired sticky window so the provider hands out a fresh IP."""
    return SESSION_RE.sub("", raw).replace("--", "-")
