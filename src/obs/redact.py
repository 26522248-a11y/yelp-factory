"""Secret redaction for logs, artifacts and error payloads."""

from __future__ import annotations

import re

REDACTED = "***REDACTED***"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # proxy credentials: host:port:user:pass
    (re.compile(r"(?P<head>\b[\w.\-]+:\d{2,5}:)[^\s:@]+:[^\s@]+"), r"\g<head>" + REDACTED),
    # user:pass@host
    (re.compile(r"(?P<head>\b[a-zA-Z][\w+.\-]*://)[^\s:/@]+:[^\s@]+@"), r"\g<head>" + REDACTED + "@"),
    # Bearer tokens
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\g<1>" + REDACTED),
    # key=value style secrets
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|otp|code|token|secret|api[_-]?key|refresh_token|client_secret)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,&}]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # long base64/hex blobs (OAuth tokens, encrypted blobs)
    (re.compile(r"\b(?:M\.C[^\s|\"']{40,}|CAP-[A-F0-9]{20,})\b"), REDACTED),
    # email passwords inside the `email|password|token` triple format
    (re.compile(r"(?P<head>[\w.+\-]+@[\w.\-]+\|)[^|\s]+"), r"\g<head>" + REDACTED),
]

_SECRET_FIELDS = {
    "password",
    "passwd",
    "pwd",
    "otp",
    "verification_code",
    "sms_code",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "email_password",
    "email_password_enc",
    "proxy_password",
    "raw_proxy",
    "master_key",
    "capsolver_key",
    "mcp_token",
    "license_key",
}

SENSITIVE_KEYS = _SECRET_FIELDS


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_obj(obj):
    if isinstance(obj, dict):
        return {
            key: (REDACTED if str(key).lower() in _SECRET_FIELDS else redact_obj(value))
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj
