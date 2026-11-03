from src.contextual_surface_equation import (
    evaluate_surface_conditions,
    evaluate_surface_conditions_v2,
    evaluate_surface_conditions_v3,
)


def _record(matches, wins):
    return {"matches": matches, "wins": wins, "losses": matches - wins}


def _pair(a_surface, b_surface, *, a_venue=None, b_venue=None,
          a_pace=None, b_pace=None, transition_a=False, transition_b=False):
    return {
        "status": "READY",
        "context_consistent": True,
        "surface_component": {"a": a_surface, "b": b_surface},
        "venue_component": {"a": a_venue, "b": b_venue},
        "pace_component": {"a": a_pace, "b": b_pace},
        "transition_component": {"a": transition_a, "b": transition_b},
    }


def test_small_surface_samples_are_shrunk_not_treated_as_certainty():
    result = evaluate_surface_conditions(_pair(_record(10, 8), _record(18, 9)))
    assert 0.0 < result["family_signal"] < 0.25
    assert result["reliability"] <= 0.5


def test_venue_and_pace_overlap_selects_one_specific_context_only():
    result = evaluate_surface_conditions(_pair(
        _record(40, 24), _record(40, 20),
        a_venue=_record(20, 14), b_venue=_record(20, 8),
        a_pace=_record(12, 8), b_pace=_record(12, 5),
    ))
    assert result["components"]["selected_specific_context"] == "pace_component"
    assert result["governance"]["overlapping_components_are_not_summed"] is True
    assert result["family_signal"] < 0.4


def test_transition_is_a_limited_modifier_not_a_full_vote():
    baseline = evaluate_surface_conditions(_pair(_record(30, 15), _record(30, 15)))
    transition = evaluate_surface_conditions(_pair(
        _record(30, 15), _record(30, 15), transition_a=True,
    ))
    assert baseline["family_signal"] == 0.0
    assert transition["family_signal"] == -0.12


def test_v2_keeps_transition_as_diagnostic_without_numeric_vote():
    baseline = evaluate_surface_conditions_v2(_pair(
        _record(30, 15), _record(30, 15),
    ))
    transition = evaluate_surface_conditions_v2(_pair(
        _record(30, 15), _record(30, 15), transition_a=True,
    ))

    assert transition["components"]["transition_signal"] == -1.0
    assert transition["components"]["transition_adjustment"] == 0.0
    assert transition["family_signal"] == baseline["family_signal"] == 0.0
    assert transition["governance"]["transition_is_diagnostic_only"] is True


def test_v3_keeps_specific_context_visible_without_numeric_vote():
    plain = evaluate_surface_conditions_v3(_pair(
        _record(40, 24), _record(40, 20),
    ))
    contextual = evaluate_surface_conditions_v3(_pair(
        _record(40, 24), _record(40, 20),
        a_venue=_record(20, 14), b_venue=_record(20, 8),
        a_pace=_record(12, 8), b_pace=_record(12, 5),
    ))

    assert contextual["components"]["selected_specific_context"] == "pace_component"
    assert contextual["components"]["specific_context_adjustment"] == 0.0
    assert contextual["family_signal"] == plain["family_signal"]
    assert contextual["governance"]["specific_context_is_diagnostic_only"] is True


def test_missing_bilateral_surface_sample_is_not_neutral():
    result = evaluate_surface_conditions(_pair(_record(10, 6), None))
    assert result["status"] == "INSUFFICIENT_BILATERAL_SURFACE_SAMPLE"
    assert result["family_signal"] is None


def test_context_mismatch_fails_closed():
    result = evaluate_surface_conditions({
        "status": "CONTEXT_MISMATCH", "context_consistent": False,
    })
    assert result["status"] == "CONTEXT_NOT_READY"
    assert result["family_signal"] is None
    assert result["production_effect"] is False
