"""E-37: Arkose FunCaptcha is mapped to the dedicated solver task type."""

from __future__ import annotations

from adapters.captcha import ARKOSE, RECAPTCHA_V2, RECAPTCHA_V3, CapsolverSolver


def test_E37_arkose_task_type():
    solver = CapsolverSolver("key")
    assert solver._task_type(ARKOSE) == "FunCaptchaTaskProxyLess"


def test_E37_recaptcha_types():
    solver = CapsolverSolver("key")
    assert solver._task_type(RECAPTCHA_V2) == "ReCaptchaV2TaskProxyLess"
    assert solver._task_type(RECAPTCHA_V3) == "ReCaptchaV3TaskProxyLess"


def test_E37_unknown_kind_falls_back_to_v2():
    solver = CapsolverSolver("key")
    assert solver._task_type("mystery") == "ReCaptchaV2TaskProxyLess"
