"""Parsers for email/proxy import files (spec v1.1, P-01..P-12)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PROXY_URL_RE = re.compile(
    r"^(?P<scheme>https?|socks5?)://(?:(?P<user>[^:@]+):(?P<pw>[^@]+)@)?(?P<host>[^:/]+):(?P<port>\d+)$"
)
# Telegram exports often contain ready-made curl commands:
#   curl -x pr.oxylabs.io:7777 -U "customer-mobile_x-cc-us:secret" https://ip.oxylabs.io/location
CURL_PROXY_RE = re.compile(
    r"-x\s+(?P<host>[^\s:/]+):(?P<port>\d+)"
    r".*?(?:-U|--proxy-user)\s+[\"'](?P<user>[^:\"']+):(?P<pw>[^\"']+)[\"']",
    re.IGNORECASE,
)


@dataclass
class ParsedEmail:
    mailbox_email: str
    mailbox_password: str
    refresh_token: str
    client_id: str
    alias: str
    full_name: str | None = None
    zip_code: str | None = None
    alias_generated: bool = False


@dataclass
class ParsedProxy:
    raw: str
    host: str
    port: int
    username: str
    password: str


@dataclass
class RowError:
    line: int
    reason: str
    raw: str


@dataclass
class ParseReport:
    rows: list = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    duplicates: int = 0

    @property
    def total(self) -> int:
        return len(self.rows) + len(self.errors) + self.duplicates


def _read_lines(text: str) -> list[str]:
    # P-01: handle UTF-8 BOM and CRLF from Windows editors.
    return text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _split(line: str) -> list[str]:
    for sep in ("|", "\t", ";"):
        if sep in line:
            return [part.strip() for part in line.split(sep)]
    return [line.strip()]


def parse_email_line(line: str, *, default_client_id: str, default_domain: str) -> ParsedEmail:
    parts = _split(line)
    if len(parts) < 3:
        raise ValueError("missing_field")
    mailbox_email, password, token = parts[0], parts[1], parts[2]
    if not EMAIL_RE.match(mailbox_email):
        raise ValueError("invalid_email")
    if not password:
        raise ValueError("missing_password")
    if len(token) < 20:
        raise ValueError("invalid_token")
    client_id = parts[3] if len(parts) > 3 and parts[3] else default_client_id
    alias = parts[4] if len(parts) > 4 and parts[4] else ""
    generated = False
    if not alias:
        local = mailbox_email.split("@")[0].lower()
        alias = f"{local}{_suffix(mailbox_email)}@{default_domain}"
        generated = True
    if not EMAIL_RE.match(alias):
        raise ValueError("invalid_alias")
    return ParsedEmail(
        mailbox_email=mailbox_email,
        mailbox_password=password,
        refresh_token=token,
        client_id=client_id,
        alias=alias,
        full_name=parts[5] if len(parts) > 5 and parts[5] else None,
        zip_code=parts[6] if len(parts) > 6 and parts[6] else None,
        alias_generated=generated,
    )


def _suffix(mailbox_email: str) -> str:
    digest = sum(ord(ch) for ch in mailbox_email)
    return str(digest % 10_000).zfill(3)


def parse_proxy_line(line: str) -> ParsedProxy:
    line = line.strip()
    if not line:
        raise ValueError("empty")
    curl = CURL_PROXY_RE.search(line)
    if curl:
        # Telegram proxy export: curl -x host:port -U "user:pass" <url>
        host, port = curl.group("host"), int(curl.group("port"))
        username, password = curl.group("user"), curl.group("pw")
        if not username or not password:
            raise ValueError("missing_field")
        if not 1 <= port <= 65535:
            raise ValueError("invalid_port")
        raw = f"{host}:{port}:{username}:{password}"
        return ParsedProxy(raw=raw, host=host, port=port, username=username, password=password)
    match = PROXY_URL_RE.match(line)
    if match:
        host, port = match.group("host"), int(match.group("port"))
        username, password = match.group("user") or "", match.group("pw") or ""
        raw = f"{host}:{port}:{username}:{password}"
    else:
        # P-04: password may contain ':', split on the first three separators only.
        parts = line.split(":", 3)
        if len(parts) != 4:
            raise ValueError("invalid_format")
        host, port_s, username, password = parts
        if not host or not username or not password:
            raise ValueError("missing_field")
        try:
            port = int(port_s)
        except ValueError as exc:
            raise ValueError("invalid_port") from exc
        raw = f"{host}:{port}:{username}:{password}"
    if not 1 <= port <= 65535:
        raise ValueError("invalid_port")
    return ParsedProxy(raw=raw, host=host, port=port, username=username, password=password)


def parse_emails(
    text: str,
    *,
    default_client_id: str,
    default_domain: str,
    existing: set[str] | None = None,
) -> ParseReport:
    """Parse a whole email file. ``existing`` holds mailbox_email/alias already in DB."""
    report = ParseReport()
    seen: set[str] = set()
    existing = existing or set()
    for index, line in enumerate(_read_lines(text), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = parse_email_line(line, default_client_id=default_client_id, default_domain=default_domain)
        except ValueError as exc:
            report.errors.append(RowError(index, str(exc), _mask(line)))
            continue
        keys = {parsed.mailbox_email.lower(), parsed.alias.lower()}
        if keys & seen or keys & {value.lower() for value in existing}:
            report.duplicates += 1
            continue
        seen |= keys
        report.rows.append(parsed)
    return report


def parse_proxies(text: str, *, existing: set[str] | None = None) -> ParseReport:
    report = ParseReport()
    seen: set[str] = set()
    existing = existing or set()
    for index, line in enumerate(_read_lines(text), start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        try:
            parsed = parse_proxy_line(line)
        except ValueError as exc:
            report.errors.append(RowError(index, str(exc), _mask(line)))
            continue
        if parsed.raw in seen or parsed.raw in existing:
            report.duplicates += 1
            continue
        seen.add(parsed.raw)
        report.rows.append(parsed)
    return report


def _mask(line: str) -> str:
    """Keep import errors useful without leaking secrets into logs/UI."""
    if "-U " in line or "--proxy-user" in line:
        return "curl ***"
    parts = _split(line)
    if len(parts) >= 2:
        return f"{parts[0][:3]}***"
    return "***"


def read_file(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig", errors="replace")
