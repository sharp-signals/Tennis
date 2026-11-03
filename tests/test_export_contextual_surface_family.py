from scripts.export_contextual_surface_family import build_contract


def _profile(improvement=0.02):
    return {
        "status": "HOLDOUT_SUPPORTED",
        "intercept": 0.0,
        "coefficients": {"exact_surface_career_margin_shrunk": 0.4},
        "preprocessor": {"method": "test"},
        "selected_l1_on_validation": 0.0,
        "fixed_l2": 0.01,
        "features": ["exact_surface_career_margin_shrunk"],
        "holdout": {"log_loss_improvement": improvement},
    }


def _report():
    contexts = ("hard_outdoor", "hard_indoor", "clay", "grass")
    return {
        "context_comparisons": {
            tour: {
                context: {
                    "source_targets": 1000,
                    "paired_holdout_targets": 200,
                    "profiles": {
                        "surface_exact_career_seasons_shrunk": _profile(),
                    },
                }
                for context in contexts
            }
            for tour in ("atp", "wta")
        },
    }


def test_surface_contract_keeps_wta_indoor_diagnostic_only():
    contract = build_contract(_report())
    assert contract["contexts"]["wta"]["hard_indoor"]["numeric_vote_enabled"] is False
    assert contract["contexts"]["atp"]["hard_indoor"]["numeric_vote_enabled"] is True
    assert contract["transition_policy"]["automatic_vote"] is False
    assert contract["pace_policy"]["automatic_vote"] is False


def test_surface_contract_never_authorizes_market_or_production():
    contract = build_contract(_report())
    assert contract["market_used"] is False
    assert contract["production_effect"] is False
    assert contract["fair_odd_eligible"] is False
    assert contract["promotion_authorized"] is False
