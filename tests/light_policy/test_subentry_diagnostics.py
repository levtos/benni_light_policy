"""Subentry fallthrough reasons remain visible without changing the chosen plan."""
from __future__ import annotations

import lp_const as C
import lp_policy as P


def _gaming_context() -> P.Context:
    return P.Context(
        activity_state=C.ACTIVITY_GAMING,
        media_device="ps5",
        day_state="late_evening",
        season=C.SEASON_AUTUMN,
    )


def _diagnostics(
    source_id: str, classifier_value: str | None, mappings: object
) -> list[dict[str, str]]:
    return P.mapping_subentry_diagnostics(
        "ps5-entry", C.SUBENTRY_GAMING, source_id, classifier_value,
        mappings, _gaming_context(),
    )


def test_empty_gaming_mappings_visible_and_distinct_from_no_subentry() -> None:
    plan = P.decide(
        _gaming_context(), lux_gate_on=True, startup_ready=True,
        apply_enabled=True, manual_off_active=False,
    )
    assert plan.subentry_diagnostics == []  # no Gaming subentry

    plan.subentry_diagnostics.extend(_diagnostics("ps5", "1", {}))
    assert plan.mode == "late_evening"
    assert plan.as_dict()["subentry_diagnostics"] == [{
        "subentry_id": "ps5-entry", "type": "gaming", "source_id": "ps5",
        "code": "missing_mappings",
    }]
    assert "gaming:ps5:missing_mappings" in plan.debug_reason
    assert plan.apply_allowed is True


def test_empty_gaming_source_id_visible() -> None:
    diagnostics = _diagnostics("", "1", {"1": "cinema"})
    assert diagnostics == [{
        "subentry_id": "ps5-entry", "type": "gaming", "code": "missing_source_id",
    }]
    plan = P.decide(
        _gaming_context(), lux_gate_on=True, startup_ready=True,
        apply_enabled=True, manual_off_active=False,
    )
    plan.subentry_diagnostics.extend(diagnostics)
    assert "gaming:ps5-entry:missing_source_id" in plan.debug_reason


def test_unknown_gaming_classifier_visible_as_separate_case() -> None:
    diagnostics = _diagnostics("ps5", "3", {"1": "cinema"})
    assert diagnostics == [{
        "subentry_id": "ps5-entry", "type": "gaming", "source_id": "ps5",
        "code": "classifier_unmapped", "classifier_value": "3",
    }]
    plan = P.decide(
        _gaming_context(), lux_gate_on=True, startup_ready=True,
        apply_enabled=True, manual_off_active=False,
    )
    plan.subentry_diagnostics.extend(diagnostics)
    assert "gaming:ps5:classifier_unmapped=3" in plan.debug_reason
    fallback = P.decide(
        _gaming_context(), lux_gate_on=True, startup_ready=True,
        apply_enabled=True, manual_off_active=False,
        extra_policies=[P.make_gaming_policy("ps5", "3", {"1": "cinema"})],
    )
    assert fallback.mode == "late_evening"


def test_music_missing_mapping_and_inactive_gaming_do_not_mask_pc_success() -> None:
    music = P.mapping_subentry_diagnostics(
        "music-entry", C.SUBENTRY_MUSIC, "", "party", {}, _gaming_context(),
    )
    assert music == [{
        "subentry_id": "music-entry", "type": "music", "code": "missing_mappings",
    }]
    assert P.mapping_subentry_diagnostics(
        "pc-entry", C.SUBENTRY_GAMING, "pc", "2", {"2": "overwatch"},
        _gaming_context(),
    ) == []
