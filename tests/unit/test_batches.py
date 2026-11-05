"""Batch stage derivation and next-action rules (pure helpers)."""

from __future__ import annotations

from core.batches import next_action_for, stage_for_state


def test_stage_registering_before_submit():
    assert stage_for_state("NEW") == "REGISTERING"
    assert stage_for_state("FORM_FILLED") == "REGISTERING"


def test_stage_created_between_submit_and_active():
    assert stage_for_state("SUBMITTED") == "CREATED"
    assert stage_for_state("ONBOARDED") == "CREATED"


def test_stage_ready_before_first_session():
    assert stage_for_state("ACTIVE", day=1, has_session=False) == "READY"


def test_stage_warming_phases():
    assert stage_for_state("ACTIVE", day=2, has_session=True) == "WARM_P0"
    assert stage_for_state("WARMING", day=4, has_session=True) == "WARM_P1"
    assert stage_for_state("WARMING", day=8, has_session=True) == "WARM_P2"
    assert stage_for_state("WARMING", day=15, has_session=True) == "WARM_P3"
    assert stage_for_state("WARMING", day=25, has_session=True) == "WARM_P4"
    assert stage_for_state("WARMING", day=40, has_session=True) == "MATURE"


def test_terminal_states_are_kept():
    for state in ("QUARANTINED", "RESTRICTED", "SUSPENDED", "DEAD"):
        assert stage_for_state(state) == state


def test_next_action_quarantine_recoverable_only_after_submit():
    assert next_action_for("QUARANTINED", submitted_done=True) == "recover"
    assert next_action_for("QUARANTINED", submitted_done=False) == "skip"


def test_next_action_fills_missing_profile_fields():
    assert next_action_for("ACTIVE", has_avatar=False, profile_done=True) == "avatar"
    assert next_action_for("WARMING", has_avatar=True, profile_done=False) == "profile"
    assert next_action_for("WARMING", has_avatar=True, profile_done=True, warm_due=True) == "warm"
    assert next_action_for("WARMING", has_avatar=True, profile_done=True, warm_due=False) == "idle"


def test_next_action_onboarded_needs_resume():
    assert next_action_for("ONBOARDED") == "onboard"
