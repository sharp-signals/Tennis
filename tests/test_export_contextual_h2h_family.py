from scripts.export_contextual_h2h_family import build_contract


def test_contract_keeps_h2h_out_of_production_and_fair_odd():
    comparison = {
        "universes": {
            "atp": {
                "selected_on_validation": "h2h_recent_context_modifier_v1",
                "candidates": {"h2h_global_shrunk_v1": {"status": "HOLDOUT_SUPPORTED", "holdout": {}}},
            },
        },
    }
    contract = build_contract(comparison)
    assert contract["status"] == "FAMILY_SHADOW_ONLY"
    assert contract["selection"]["atp"]["deployed_family_candidate"] == "h2h_global_shrunk_v1"
    assert contract["guards"]["fair_odd_fitted"] is False
    assert contract["guards"]["promotion_authorized"] is False
