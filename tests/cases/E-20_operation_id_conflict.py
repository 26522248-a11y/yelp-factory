"""E-20: same operation_id with a different payload must not create a second profile."""

from __future__ import annotations

import pytest

from adapters.base import GPMConflict
from adapters.gpm_ops import ensure_profile
from tests.fakes import FakeGPM

pytestmark = pytest.mark.usefixtures("db_ready")


def test_E20_conflicting_payload_is_rejected():
    gpm = FakeGPM()
    op = "reg:test-e20"
    profile, reused = ensure_profile(gpm, operation_id=op, name="yf-e20", create_kwargs={"raw_proxy": "1.1.1.1:1:u:p"})
    assert reused is False
    assert profile.id

    same, reused_again = ensure_profile(gpm, operation_id=op, name="yf-e20", create_kwargs={"raw_proxy": "1.1.1.1:1:u:p"})
    assert reused_again is True and same.id == profile.id
    assert len(gpm.create_calls) == 1

    with pytest.raises(GPMConflict):
        ensure_profile(gpm, operation_id=op, name="yf-e20", create_kwargs={"raw_proxy": "2.2.2.2:2:u:p"})
