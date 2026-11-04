"""Import parsers (P-01..P-12)."""

from __future__ import annotations

from core.importers import parse_email_line, parse_emails, parse_proxies, parse_proxy_line

CLIENT = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
TOKEN = "M.C524_BAY." + "x" * 60


def test_email_line_five_fields():
    row = parse_email_line(
        f"JonhsonElders63@hotmail.com|VjJAGiuOkX|{TOKEN}|{CLIENT}|jonhsonelders63yl3@fviainboxes.com",
        default_client_id=CLIENT,
        default_domain="fviainboxes.com",
    )
    assert row.mailbox_email == "JonhsonElders63@hotmail.com"
    assert row.alias == "jonhsonelders63yl3@fviainboxes.com"
    assert row.alias_generated is False


def test_p01_bom_and_crlf():
    text = "\ufeffa@b.com|pass|" + TOKEN + "|" + CLIENT + "|a@fviainboxes.com\r\n"
    report = parse_emails(text, default_client_id=CLIENT, default_domain="fviainboxes.com")
    assert len(report.rows) == 1
    assert not report.errors


def test_p02_missing_field_is_reported_with_line():
    text = "\nbad-line\na@b.com|pass|" + TOKEN + "|" + CLIENT + "|a@fviainboxes.com"
    report = parse_emails(text, default_client_id=CLIENT, default_domain="fviainboxes.com")
    assert len(report.rows) == 1
    assert report.errors[0].line == 2
    assert report.errors[0].reason == "missing_field"


def test_p04_proxy_password_with_colon():
    row = parse_proxy_line("pr.oxylabs.io:7777:user:pa:ss:word")
    assert row.host == "pr.oxylabs.io"
    assert row.port == 7777
    assert row.password == "pa:ss:word"


def test_proxy_url_form_is_normalised():
    row = parse_proxy_line("http://user:pw@1.2.3.4:8080")
    assert row.raw == "1.2.3.4:8080:user:pw"


def test_curl_export_form_is_accepted():
    line = 'curl -x pr.oxylabs.io:7777 -U "customer-mobile_abc-cc-us:LDm9ij+hprnQ" https://ip.oxylabs.io/location'
    row = parse_proxy_line(line)
    assert row.host == "pr.oxylabs.io"
    assert row.port == 7777
    assert row.username == "customer-mobile_abc-cc-us"
    assert row.password == "LDm9ij+hprnQ"
    assert row.raw == "pr.oxylabs.io:7777:customer-mobile_abc-cc-us:LDm9ij+hprnQ"


def test_curl_error_line_does_not_leak_secret():
    report = parse_proxies('curl -x pr.oxylabs.io:0 -U "user:supersecret" https://x')
    assert report.errors[0].raw == "curl ***"


def test_invalid_port_rejected():
    try:
        parse_proxy_line("host:99999:u:p")
    except ValueError as exc:
        assert str(exc) == "invalid_port"
    else:
        raise AssertionError("should reject")


def test_p11_empty_file_has_no_rows():
    report = parse_emails("\n\n# comment\n", default_client_id=CLIENT, default_domain="fviainboxes.com")
    assert report.rows == []
    assert report.total == 0


def test_duplicate_inside_file_counted_once():
    line = f"a@b.com|pass|{TOKEN}|{CLIENT}|a@fviainboxes.com"
    report = parse_emails(line + "\n" + line, default_client_id=CLIENT, default_domain="fviainboxes.com")
    assert len(report.rows) == 1
    assert report.duplicates == 1


def test_existing_pool_rows_are_skipped():
    line = f"a@b.com|pass|{TOKEN}|{CLIENT}|a@fviainboxes.com"
    report = parse_emails(
        line, default_client_id=CLIENT, default_domain="fviainboxes.com", existing={"a@b.com"}
    )
    assert report.rows == []
    assert report.duplicates == 1


def test_alias_is_generated_when_missing():
    row = parse_email_line(
        f"a@b.com|pass|{TOKEN}|{CLIENT}",
        default_client_id=CLIENT,
        default_domain="fviainboxes.com",
    )
    assert row.alias.endswith("@fviainboxes.com")
    assert row.alias_generated is True


def test_proxy_file_parsing_and_dedupe():
    text = "1.1.1.1:8000:u:p\n1.1.1.1:8000:u:p\nbadline\n"
    report = parse_proxies(text)
    assert len(report.rows) == 1
    assert report.duplicates == 1
    assert report.errors[0].reason == "invalid_format"


def test_error_rows_are_masked():
    report = parse_emails(
        "secret@mail.com|supersecret|short",
        default_client_id=CLIENT,
        default_domain="fviainboxes.com",
    )
    assert "supersecret" not in report.errors[0].raw
    assert "sec***" in report.errors[0].raw
