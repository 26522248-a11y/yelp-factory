from __future__ import annotations

from obs.redact import redact_obj, redact_text


def test_redacts_proxy_credentials():
    raw = "pr.oxylabs.io:7777:customer-mobile_abc:brfcnh0W3=bN"
    assert "brfcnh0W3" not in redact_text(raw)
    assert "pr.oxylabs.io:7777:" in redact_text(raw)


def test_redacts_url_credentials():
    text = "http://user:secret@10.0.0.1:8080/path"
    assert "secret" not in redact_text(text)


def test_redacts_key_value_pairs():
    text = 'password="Hunter2!" otp=123456 token: abcdef123456'
    out = redact_text(text)
    for secret in ("Hunter2!", "123456", "abcdef123456"):
        assert secret not in out


def test_redacts_email_password_triple():
    line = "someone@hotmail.com|PteNqaaFuP|M.C543_BL2.0.U.MsaArtifacts.-CgMlLfZ2sM9XsfW227kfNc9pAjBJHymUglJ34dPX"
    out = redact_text(line)
    assert "PteNqaaFuP" not in out
    assert "M.C543" not in out


def test_redacts_object_fields_by_name():
    payload = {"email": "a@b.com", "password": "x", "otp": "123456", "nested": {"token": "t"}}
    out = redact_obj(payload)
    assert out["password"] == "***REDACTED***"
    assert out["otp"] == "***REDACTED***"
    assert out["nested"]["token"] == "***REDACTED***"
    assert out["email"] == "a@b.com"


def test_capsolver_key_is_redacted():
    key = "CAP-13DD600012FAB8F5E2591D4DF6A3397947BF8D1A89ED5399FB041917D5321E60"
    assert key not in redact_text(f"key={key}")
