"""Scale-free governance of realized contextual-family contributions."""

from __future__ import annotations


PRIMARY_FAMILIES = ("recent_form", "structural_strength")
SECONDARY_FAMILIES = ("surface_conditions", "matchup_h2h", "serve_return")


def govern_realized_family_contributions(
    contributions: dict[str, float],
) -> tuple[dict[str, float], dict[str, float | bool]]:
    """Bound secondary impact by the *realized* primary evidence budget.

    The v8 coefficient hierarchy is necessary but insufficient because family
    logits use different scales. This projection is deliberately scale-free:
    its limits are derived from the two primary contributions in the same
    match, not from hand-picked percentage weights.
    """
    governed = {
        family: float(contributions.get(family, 0.0))
        for family in (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
    }
    primary_budget = sum(abs(governed[family]) for family in PRIMARY_FAMILIES)
    secondary_budget_before = sum(
        abs(governed[family]) for family in SECONDARY_FAMILIES
    )
    primary_average = primary_budget / len(PRIMARY_FAMILIES)
    scale = 1.0
    if secondary_budget_before > 0.0:
        if primary_budget <= 0.0:
            scale = 0.0
        else:
            largest_secondary = max(
                abs(governed[family]) for family in SECONDARY_FAMILIES
            )
            if largest_secondary > primary_average:
                scale = min(scale, primary_average / largest_secondary)
            if secondary_budget_before > primary_budget:
                scale = min(scale, primary_budget / secondary_budget_before)
    for family in SECONDARY_FAMILIES:
        governed[family] *= scale
    secondary_budget_after = sum(
        abs(governed[family]) for family in SECONDARY_FAMILIES
    )
    largest_secondary_after = max(
        (abs(governed[family]) for family in SECONDARY_FAMILIES),
        default=0.0,
    )
    return governed, {
        "applied": scale < 1.0 - 1e-12,
        "secondary_scale": float(scale),
        "primary_absolute_budget": float(primary_budget),
        "primary_average_absolute_impact": float(primary_average),
        "secondary_absolute_budget_before": float(secondary_budget_before),
        "secondary_absolute_budget_after": float(secondary_budget_after),
        "largest_secondary_absolute_impact_after": float(
            largest_secondary_after
        ),
    }


def govern_consensus_aware_family_contributions(
    contributions: dict[str, float],
) -> tuple[dict[str, float], dict[str, float | bool | str]]:
    """Govern secondary evidence without crushing unanimous reinforcement.

    Conflicting or one-sided primary evidence keeps the strict v9 block cap.
    When both primary families are non-opposed and every active secondary
    family reinforces the same side, no directional conflict exists: the
    primary block authorises the side and the unanimous independent evidence
    is preserved to refine magnitude.  This prevents a secondary family from
    reversing the primary reading without crushing five-of-five consensus.
    No fixed player, match or market adjustment is introduced.
    """
    governed = {
        family: float(contributions.get(family, 0.0))
        for family in (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
    }

    def direction(value: float) -> int:
        return 1 if value > 0.0 else -1 if value < 0.0 else 0

    primary_values = [governed[family] for family in PRIMARY_FAMILIES]
    secondary_values = [governed[family] for family in SECONDARY_FAMILIES]
    primary_net = sum(primary_values)
    primary_direction = direction(primary_net)
    primary_non_opposed = bool(primary_direction) and all(
        direction(value) in (0, primary_direction) for value in primary_values
    )
    secondary_reinforces = bool(primary_direction) and all(
        direction(value) in (0, primary_direction) for value in secondary_values
    )
    consensus_reinforcement = primary_non_opposed and secondary_reinforces

    primary_budget = sum(abs(value) for value in primary_values)
    primary_average = primary_budget / len(PRIMARY_FAMILIES)
    primary_strongest = max((abs(value) for value in primary_values), default=0.0)
    secondary_budget_before = sum(abs(value) for value in secondary_values)
    largest_secondary = max((abs(value) for value in secondary_values), default=0.0)
    scale = 1.0

    if secondary_budget_before > 0.0:
        if primary_budget <= 0.0:
            scale = 0.0
        elif not consensus_reinforcement:
            if largest_secondary > primary_average:
                scale = min(scale, primary_average / largest_secondary)
            if secondary_budget_before > primary_budget:
                scale = min(scale, primary_budget / secondary_budget_before)

    for family in SECONDARY_FAMILIES:
        governed[family] *= scale
    secondary_budget_after = sum(
        abs(governed[family]) for family in SECONDARY_FAMILIES
    )
    largest_secondary_after = max(
        (abs(governed[family]) for family in SECONDARY_FAMILIES), default=0.0
    )
    return governed, {
        "applied": scale < 1.0 - 1e-12,
        "policy": (
            "UNANIMOUS_REINFORCEMENT_PRESERVED"
            if consensus_reinforcement else "STRICT_CONFLICT_BLOCK_CAP"
        ),
        "consensus_reinforcement": consensus_reinforcement,
        "secondary_scale": float(scale),
        "primary_absolute_budget": float(primary_budget),
        "primary_average_absolute_impact": float(primary_average),
        "primary_strongest_absolute_impact": float(primary_strongest),
        "secondary_absolute_budget_before": float(secondary_budget_before),
        "secondary_absolute_budget_after": float(secondary_budget_after),
        "largest_secondary_absolute_impact_after": float(
            largest_secondary_after
        ),
    }


def govern_consensus_with_individual_cap(
    contributions: dict[str, float],
    *,
    consensus_cap_basis: str = "strongest_primary",
) -> tuple[dict[str, float], dict[str, object]]:
    """Preserve unanimous evidence without letting one modifier dominate.

    Conflicting evidence uses the strict block cap.  When both primaries and
    every active secondary agree, consensus remains informative, but each
    secondary is capped at the strongest realised primary contribution.
    """
    governed = {
        family: float(contributions.get(family, 0.0))
        for family in (*PRIMARY_FAMILIES, *SECONDARY_FAMILIES)
    }

    def direction(value: float) -> int:
        return 1 if value > 0.0 else -1 if value < 0.0 else 0

    primary_values = [governed[family] for family in PRIMARY_FAMILIES]
    secondary_values = [governed[family] for family in SECONDARY_FAMILIES]
    primary_direction = direction(sum(primary_values))
    consensus = bool(primary_direction) and all(
        direction(value) in (0, primary_direction)
        for value in (*primary_values, *secondary_values)
    )
    if not consensus:
        governed, audit = govern_realized_family_contributions(governed)
        return governed, {
            **audit,
            "policy": "STRICT_CONFLICT_BLOCK_CAP",
            "consensus_reinforcement": False,
        }

    primary_strongest = max((abs(value) for value in primary_values), default=0.0)
    primary_total = sum(abs(value) for value in primary_values)
    if consensus_cap_basis == "strongest_primary":
        consensus_cap = primary_strongest
    elif consensus_cap_basis == "aligned_primary_total":
        consensus_cap = primary_total
    else:
        raise ValueError(f"unsupported consensus cap basis: {consensus_cap_basis}")
    capped_families = []
    for family in SECONDARY_FAMILIES:
        if abs(governed[family]) > consensus_cap:
            governed[family] = (
                consensus_cap if governed[family] > 0.0 else -consensus_cap
            )
            capped_families.append(family)
    return governed, {
        "applied": bool(capped_families),
        "policy": "CONSENSUS_WITH_INDIVIDUAL_SECONDARY_CAP",
        "consensus_reinforcement": True,
        "primary_strongest_absolute_impact": primary_strongest,
        "primary_total_absolute_impact": primary_total,
        "consensus_cap_basis": consensus_cap_basis,
        "consensus_cap_absolute_impact": consensus_cap,
        "capped_families": capped_families,
    }
