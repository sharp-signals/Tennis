from src.contextual_h2h_equation import evaluate_contextual_h2h


def _match(side, **extra):
    return {
        "winner_side": side,
        "competitively_eligible": True,
        "same_surface": False,
        "same_competition_context": False,
        "days_before_cutoff": 900,
        **extra,
    }


def test_observed_none_is_neutral_coverage_not_missing():
    result = evaluate_contextual_h2h({"status": "OBSERVED_NONE", "matches": []})
    assert result["status"] == "READY_NEUTRAL"
    assert result["family_signal"] == 0.0
    assert result["reliability"] == 1.0


def test_single_match_is_strongly_shrunk_and_flagged_low_evidence():
    result = evaluate_contextual_h2h({"status": "AVAILABLE", "matches": [_match("a")]})
    assert result["family_signal"] == 0.333333
    assert result["evidence_band"] == "single_low"
    assert result["governance"]["single_match_is_low_evidence"] is True


def test_context_is_visible_but_never_added_as_second_vote():
    result = evaluate_contextual_h2h({
        "status": "AVAILABLE",
        "matches": [
            _match("a", same_surface=True, days_before_cutoff=100),
            _match("b", same_surface=False, days_before_cutoff=200),
        ],
    })
    assert result["family_signal"] == 0.0
    assert result["components"]["same_surface_matches"] == 1
    assert result["components"]["recent_730d_matches"] == 2


def test_unavailable_identity_never_becomes_neutral_vote():
    result = evaluate_contextual_h2h({"status": "IDENTITY_UNRESOLVED"})
    assert result["status"] == "UNAVAILABLE"
    assert result["family_signal"] is None
