"""E-36: low reCAPTCHA v3 score -> slow down and pre-warm longer before the next try."""

from __future__ import annotations

from core.guards import v3_throttle
from human.timing import session_length_seconds
from flows.signup import SignupFlow


def test_E36_prewarm_is_doubled_capped_at_60s():
    assert v3_throttle(20) == 40
    assert v3_throttle(45) == 60
    assert v3_throttle(60) == 60


def test_E36_sessions_have_human_length():
    for _ in range(20):
        assert 240 <= session_length_seconds() <= 720


def test_E36_captcha_failure_is_fatal_after_two_attempts():
    # The stage retry policy gives two attempts, then the account is quarantined as captcha.
    from core.state_machine import Stage
    from db.models import AccountState

    stage = [s for s in SignupFlow(settings=None, gpm=None, registry=None, email_provider=None).stages() if s.state == AccountState.CAPTCHA_SOLVED][0]
    assert stage.retry.max_attempts == 2
