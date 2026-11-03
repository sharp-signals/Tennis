from scripts.export_contextual_serve_return_family import build_contract


def test_contract_selects_circuit_specific_profiles_and_stays_secondary():
    candidate = {"status": "HOLDOUT_SUPPORTED"}
    comparison = {
        "universes": {
            "atp": {
                "candidates": {
                    "serve_return_points_recent_deviation_v1": candidate,
                },
                "incremental_after_primary_families": {
                    "status": "HOLDOUT_SUPPORTED",
                    "holdout_log_loss_improvement": 0.001,
                },
            },
            "wta": {
                "candidates": {
                    "serve_return_surface_points_shrunk_v1": candidate,
                },
                "incremental_after_primary_families": {
                    "status": "HOLDOUT_SUPPORTED",
                    "holdout_log_loss_improvement": 0.004,
                },
            },
        },
    }
    contract = build_contract(comparison)
    assert contract["selected_profiles"]["atp"]["profile"].endswith(
        "recent_deviation_v1",
    )
    assert contract["selected_profiles"]["wta"]["profile"].endswith(
        "surface_points_shrunk_v1",
    )
    assert contract["governance"]["standalone_candidate_prohibited"] is True
    assert contract["governance"]["fair_odd_fitted"] is False
