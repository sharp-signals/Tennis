from src.contextual_factor_orchestrator import (
    build_contextual_family_vector,
    build_report_family_rows,
)


def _ready(**overrides):
    observations = {
        "recent_form": {"status": "AVAILABLE"},
        "structural_strength": {"evidence_status": "BILATERAL"},
        "surface_conditions": {"status": "READY"},
        "matchup_h2h": {"status": "OBSERVED_NONE"},
        "serve_return": {"status": "READY"},
    }
    observations.update(overrides)
    return observations


def _family(vector, key):
    return next(row for row in vector["families"] if row["key"] == key)


def test_observed_but_unscored_is_not_falsely_neutral():
    vector = build_contextual_family_vector(_ready())
    recent = _family(vector, "recent_form")
    assert recent["data_state"] == "OBSERVED"
    assert recent["signal_state"] == "UNSCORED"
    assert recent["direction"] is None


def test_confirmed_zero_h2h_counts_as_coverage_without_impact():
    vector = build_contextual_family_vector(_ready())
    h2h = _family(vector, "matchup_h2h")
    assert h2h["data_state"] == "OBSERVED_NONE"
    assert h2h["signal_state"] == "NONE"
    assert vector["coverage"]["observed"] == 5


def test_missing_required_family_blocks_calibration_and_increases_uncertainty():
    vector = build_contextual_family_vector(
        _ready(recent_form={"status": "SOURCE_UNAVAILABLE"})
    )
    assert vector["calibration_ready"] is False
    assert vector["missing_data_increases_uncertainty"] is True


def test_missing_optional_service_does_not_alone_block_replay_readiness():
    vector = build_contextual_family_vector(
        _ready(serve_return={"status": "SOURCE_UNAVAILABLE"})
    )
    assert vector["calibration_ready"] is True


def test_secondary_service_cannot_replace_missing_primary_families():
    vector = build_contextual_family_vector({
        "serve_return": {"status": "READY", "direction": "a"},
    })
    assert vector["calibration_ready"] is False
    assert vector["pricing_ready"] is False
    assert vector["dependency_policy"][
        "serve_return_is_secondary_and_cannot_create_a_standalone_signal"
    ] is True


def test_market_contamination_fails_closed():
    try:
        build_contextual_family_vector(
            _ready(recent_form={"status": "AVAILABLE", "market_used": True})
        )
    except ValueError as exc:
        assert "market contamination" in str(exc)
    else:
        raise AssertionError("market contamination was accepted")


def test_production_mutation_fails_closed():
    try:
        build_contextual_family_vector(
            _ready(recent_form={"status": "AVAILABLE", "production_effect": True})
        )
    except ValueError as exc:
        assert "production mutation" in str(exc)
    else:
        raise AssertionError("production mutation was accepted")


def test_primary_disagreement_is_visible_and_not_averaged_away():
    vector = build_contextual_family_vector(_ready(
        recent_form={"status": "AVAILABLE", "direction": "a"},
        structural_strength={"status": "BILATERAL", "direction": "b"},
    ))
    assert vector["conflicts"] == ["PRIMARY_FAMILIES_DISAGREE"]
    assert vector["score"] is None
    assert vector["probability"] is None


def test_dependency_matrix_has_single_owners_and_no_component_sum():
    vector = build_contextual_family_vector(_ready())
    owners = [component for row in vector["families"] for component in row["owns"]]
    assert len(owners) == len(set(owners))
    assert vector["dependency_policy"]["single_owner_per_component"] is True
    assert vector["dependency_policy"]["component_scores_are_not_summed"] is True


def test_report_view_has_exactly_five_plain_language_rows_without_scores():
    rows = build_report_family_rows(build_contextual_family_vector(_ready()))
    assert len(rows) == 5
    assert rows[0]["label"] == "Forma recente ajustada"
    assert rows[-1]["role_label"] == "Contexto secundário"
    assert all("weight" not in row and "score" not in row for row in rows)
    assert "100" not in str(rows)


def test_maximum_certainty_is_explicitly_prohibited():
    vector = build_contextual_family_vector(_ready())
    assert vector["maximum_certainty_prohibited"] is True
    assert vector["index"] is None
    assert vector["fair_odd"] is None


def test_context_mismatch_is_not_silently_treated_as_neutral():
    vector = build_contextual_family_vector(
        _ready(surface_conditions={"status": "CONTEXT_MISMATCH"})
    )
    surface = _family(vector, "surface_conditions")
    assert surface["data_state"] == "MISSING_DATA"
    assert surface["signal_state"] == "UNAVAILABLE"
    assert "CONTEXT_MISMATCH" in surface["reason_codes"]
