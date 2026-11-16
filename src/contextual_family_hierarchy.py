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
