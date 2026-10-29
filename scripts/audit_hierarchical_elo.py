"""Auditoria cronologica do prior Elo ATP e do ajuste dos fatores.

O objetivo e testar, sem odds como preditor, se o Elo de superficie deve ser
encolhido para o Elo global quando a amostra no piso ainda e curta. A escolha
dos hiperparametros usa 2025 e o resultado final e medido apenas em 2026.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass

from calibrate_elo_probability import Match, _solve, elo_features, load_matches
from calibrate_structural_probability import Row, load_rows


@dataclass(frozen=True)
class EloState:
    global_ratings: dict[str, float]
    surface_ratings: dict[tuple[str, str], float]
    surface_matches: dict[tuple[str, str], int]


def logistic(value: float) -> float:
    value = min(20.0, max(-20.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def blend_weight(matches_a: int, matches_b: int, prior_matches: float) -> float:
    effective = min(matches_a, matches_b)
    return effective / (effective + prior_matches) if effective else 0.0


def blended_logit(
    global_a: float,
    global_b: float,
    surface_a: float,
    surface_b: float,
    surface_matches_a: int,
    surface_matches_b: int,
    *,
    prior_matches: float,
    scale: float,
) -> float:
    elo_scale = math.log(10.0) / 400.0
    global_value = (global_a - global_b) * elo_scale
    surface_value = (surface_a - surface_b) * elo_scale
    weight = blend_weight(surface_matches_a, surface_matches_b, prior_matches)
    return scale * ((1.0 - weight) * global_value + weight * surface_value)


def score(observations: list[tuple[float, float]]) -> dict:
    if not observations:
        return {"n": 0, "brier": None, "log_loss": None}
    brier = sum((probability - target) ** 2 for probability, target in observations)
    log_loss = -sum(
        target * math.log(max(probability, 1e-12))
        + (1.0 - target) * math.log(max(1.0 - probability, 1e-12))
        for probability, target in observations
    )
    return {
        "n": len(observations),
        "brier": round(brier / len(observations), 6),
        "log_loss": round(log_loss / len(observations), 6),
    }


def historical_predictions(
    matches: list[Match], *, k: float, prior_matches: float, scale: float
) -> dict[int, list[tuple[float, float]]]:
    global_ratings = defaultdict(lambda: 1500.0)
    surface_ratings = defaultdict(lambda: 1500.0)
    surface_counts = defaultdict(int)
    predictions: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for match in matches:
        if match.scope != "main":
            continue
        winner_surface = (match.surface, match.winner)
        loser_surface = (match.surface, match.loser)
        logit = blended_logit(
            global_ratings[match.winner], global_ratings[match.loser],
            surface_ratings[winner_surface], surface_ratings[loser_surface],
            surface_counts[winner_surface], surface_counts[loser_surface],
            prior_matches=prior_matches, scale=scale,
        )
        predictions[match.played_on.year].append((logistic(logit), 1.0))

        global_expectation = expected(global_ratings[match.winner], global_ratings[match.loser])
        global_change = k * (1.0 - global_expectation)
        global_ratings[match.winner] += global_change
        global_ratings[match.loser] -= global_change

        surface_expectation = expected(
            surface_ratings[winner_surface], surface_ratings[loser_surface]
        )
        surface_change = k * (1.0 - surface_expectation)
        surface_ratings[winner_surface] += surface_change
        surface_ratings[loser_surface] -= surface_change
        surface_counts[winner_surface] += 1
        surface_counts[loser_surface] += 1
    return predictions


def choose_historical_model(matches: list[Match]) -> tuple[dict, dict]:
    candidates = []
    for k in (16.0, 24.0, 32.0, 40.0):
        for prior_matches in (5.0, 10.0, 20.0, 40.0, 80.0):
            for scale in (0.75, 1.0, 1.25):
                predictions = historical_predictions(
                    matches, k=k, prior_matches=prior_matches, scale=scale
                )
                validation = score(predictions.get(2025, []))
                candidates.append((validation["log_loss"], k, prior_matches, scale))
    _, k, prior_matches, scale = min(candidates)
    predictions = historical_predictions(
        matches, k=k, prior_matches=prior_matches, scale=scale
    )
    selected = {"k": k, "prior_matches": prior_matches, "scale": scale}
    metrics = {
        "validation_2025": score(predictions.get(2025, [])),
        "test_2026": score(predictions.get(2026, [])),
    }
    return selected, metrics


def snapshot_prior_logits(
    rows: list[Row], matches: list[Match], *, k: float,
    prior_matches: float, scale: float,
) -> dict[str, float]:
    main_matches = [match for match in matches if match.scope == "main"]
    global_ratings = defaultdict(lambda: 1500.0)
    surface_ratings = defaultdict(lambda: 1500.0)
    surface_counts = defaultdict(int)
    result = {}
    index = 0
    for row in sorted(rows, key=lambda item: (item.analyzed_at, item.key)):
        cutoff = row.analyzed_at.date()
        while index < len(main_matches) and main_matches[index].played_on < cutoff:
            match = main_matches[index]
            winner_surface = (match.surface, match.winner)
            loser_surface = (match.surface, match.loser)
            global_change = k * (
                1.0 - expected(global_ratings[match.winner], global_ratings[match.loser])
            )
            global_ratings[match.winner] += global_change
            global_ratings[match.loser] -= global_change
            surface_change = k * (
                1.0 - expected(
                    surface_ratings[winner_surface], surface_ratings[loser_surface]
                )
            )
            surface_ratings[winner_surface] += surface_change
            surface_ratings[loser_surface] -= surface_change
            surface_counts[winner_surface] += 1
            surface_counts[loser_surface] += 1
            index += 1
        player_a, player_b = row.player_a.casefold(), row.player_b.casefold()
        # load_rows preserva acentos; os nomes do historico ja chegam normalizados
        from calibrate_elo_probability import _name, _surface
        player_a, player_b = _name(player_a), _name(player_b)
        surface = _surface(row.surface)
        key_a, key_b = (surface, player_a), (surface, player_b)
        result[row.key] = blended_logit(
            global_ratings[player_a], global_ratings[player_b],
            surface_ratings[key_a], surface_ratings[key_b],
            surface_counts[key_a], surface_counts[key_b],
            prior_matches=prior_matches, scale=scale,
        )
    return result


def factor_value(row: Row, priors: dict[str, float], *, aligned_only: bool) -> float:
    value = row.factor_predictor
    if aligned_only and value * priors[row.key] <= 0:
        return 0.0
    return value


def fit_factor_gamma(
    rows: list[Row], priors: dict[str, float], *, ridge: float,
    aligned_only: bool = False,
) -> float:
    gamma = 0.0
    for _ in range(100):
        gradient = -ridge * gamma
        hessian = ridge
        for row in rows:
            factor = factor_value(row, priors, aligned_only=aligned_only)
            probability = logistic(priors[row.key] + gamma * factor)
            gradient += factor * (row.target_a - probability)
            hessian += factor * factor * probability * (1.0 - probability)
        change = gradient / hessian if hessian else 0.0
        gamma = max(0.0, gamma + change)
        if abs(change) < 1e-10:
            break
    return gamma


def quality_adjusted_families(row: Row) -> tuple[float, ...]:
    quality = (
        min(1.0, abs(row.factor_predictor / row.signed_strength))
        if abs(row.signed_strength) > 1e-12 else 0.0
    )
    return tuple(value * quality for value in row.family_predictors)


def fit_family_adjustments(
    rows: list[Row], priors: dict[str, float], *, ridge: float
) -> tuple[float, ...]:
    size = len(rows[0].family_predictors)
    coefficients = [0.0] * size
    for _ in range(100):
        gradient = [-ridge * value for value in coefficients]
        hessian = [
            [ridge if a == b else 0.0 for b in range(size)]
            for a in range(size)
        ]
        for row in rows:
            features = quality_adjusted_families(row)
            probability = logistic(
                priors[row.key]
                + sum(value * feature for value, feature in zip(coefficients, features))
            )
            error = row.target_a - probability
            variance = probability * (1.0 - probability)
            for a in range(size):
                gradient[a] += features[a] * error
                for b in range(size):
                    hessian[a][b] += features[a] * features[b] * variance
        delta = _solve(hessian, gradient)
        updated = [max(0.0, value + change) for value, change in zip(coefficients, delta)]
        if max(abs(after - before) for before, after in zip(coefficients, updated)) < 1e-10:
            coefficients = updated
            break
        coefficients = updated
    return tuple(coefficients)


def snapshot_family_score(
    rows: list[Row], priors: dict[str, float], coefficients: tuple[float, ...]
) -> dict:
    return score([
        (
            logistic(
                priors[row.key] + sum(
                    value * feature for value, feature
                    in zip(coefficients, quality_adjusted_families(row))
                )
            ),
            row.target_a,
        )
        for row in rows
    ])


def snapshot_score(
    rows: list[Row], priors: dict[str, float], gamma: float,
    *, aligned_only: bool = False,
) -> dict:
    return score([
        (logistic(
            priors[row.key]
            + gamma * factor_value(row, priors, aligned_only=aligned_only)
        ), row.target_a)
        for row in rows
    ])


def calibration_bins(rows: list[Row], probabilities: dict[str, float]) -> list[dict]:
    bins = []
    for lower in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        upper = lower + 0.1
        selected = [row for row in rows if lower <= probabilities[row.key] < upper]
        if selected:
            bins.append({
                "range": f"{lower:.1f}-{upper:.1f}",
                "n": len(selected),
                "mean_probability": round(
                    sum(probabilities[row.key] for row in selected) / len(selected), 4
                ),
                "observed_win_rate": round(
                    sum(row.target_a for row in selected) / len(selected), 4
                ),
            })
    return bins


def main() -> None:
    matches = load_matches()
    selected, history_metrics = choose_historical_model(matches)
    rows = [row for row in load_rows() if row.segment == "atp"]
    priors = snapshot_prior_logits(rows, matches, **selected)
    train_end, validation_end = int(len(rows) * 0.60), int(len(rows) * 0.80)
    train, validation, test = rows[:train_end], rows[train_end:validation_end], rows[validation_end:]
    candidates = []
    for ridge in (0.5, 1.0, 2.0, 5.0, 10.0):
        gamma = fit_factor_gamma(train, priors, ridge=ridge)
        candidates.append((snapshot_score(validation, priors, gamma)["log_loss"], ridge, gamma))
    _, ridge, validation_gamma = min(candidates)
    gamma = fit_factor_gamma(rows[:validation_end], priors, ridge=ridge)
    aligned_candidates = []
    for aligned_ridge in (0.5, 1.0, 2.0, 5.0, 10.0, 20.0):
        aligned_gamma = fit_factor_gamma(
            train, priors, ridge=aligned_ridge, aligned_only=True
        )
        aligned_candidates.append((
            snapshot_score(
                validation, priors, aligned_gamma, aligned_only=True
            )["log_loss"],
            aligned_ridge,
        ))
    _, aligned_ridge = min(aligned_candidates)
    aligned_gamma = fit_factor_gamma(
        rows[:validation_end], priors, ridge=aligned_ridge, aligned_only=True
    )
    family_candidates = []
    for family_ridge in (1.0, 2.0, 5.0, 10.0, 20.0, 40.0):
        coefficients = fit_family_adjustments(train, priors, ridge=family_ridge)
        family_candidates.append((
            snapshot_family_score(validation, priors, coefficients)["log_loss"],
            family_ridge,
        ))
    _, family_ridge = min(family_candidates)
    family_coefficients = fit_family_adjustments(
        rows[:validation_end], priors, ridge=family_ridge
    )
    hierarchical_probabilities = {
        row.key: logistic(priors[row.key] + gamma * row.factor_predictor)
        for row in rows
    }
    current_features = elo_features(rows, matches, k=40.0)
    current_coefficients = (0.45733118162952946, 0.6389725434911556, 0.0, 0.559423459229921)
    current_probabilities = {
        row.key: logistic(sum(
            coefficient * feature
            for coefficient, feature in zip(current_coefficients, current_features[row.key])
        ))
        for row in rows
    }
    market_test = [row for row in test if row.market_probability_a is not None]
    diagnostics = []
    for row in rows:
        if {row.player_a.casefold(), row.player_b.casefold()} == {
            "tommy paul", "luciano darderi"
        }:
            diagnostics.append({
                "match": f"{row.player_a} vs {row.player_b}",
                "analyzed_at": row.analyzed_at.isoformat(),
                "current_probability_a": round(current_probabilities[row.key], 4),
                "hierarchical_probability_a": round(hierarchical_probabilities[row.key], 4),
                "market_probability_a": row.market_probability_a,
                "factor_predictor_quality_adjusted": round(row.factor_predictor, 4),
            })
    output = {
        "selected_historical_model": selected,
        "historical_out_of_sample": history_metrics,
        "snapshots": {
            "n": len(rows), "train_n": len(train), "validation_n": len(validation),
            "test_n": len(test), "selected_ridge": ridge,
            "validation_factor_gamma": validation_gamma,
            "refit_factor_gamma": gamma,
            "test_prior_only": snapshot_score(test, priors, 0.0),
            "test_prior_plus_quality_adjusted_factors": snapshot_score(test, priors, gamma),
            "selected_aligned_ridge": aligned_ridge,
            "aligned_factor_gamma": aligned_gamma,
            "test_prior_plus_aligned_factors": snapshot_score(
                test, priors, aligned_gamma, aligned_only=True
            ),
            "selected_family_ridge": family_ridge,
            "family_coefficients": family_coefficients,
            "test_prior_plus_factor_families": snapshot_family_score(
                test, priors, family_coefficients
            ),
            "test_current_runtime_model": score([
                (current_probabilities[row.key], row.target_a) for row in test
            ]),
            "test_market_benchmark": score([
                (row.market_probability_a, row.target_a) for row in market_test
            ]),
            "calibration_bins_hierarchical": calibration_bins(test, hierarchical_probabilities),
            "calibration_bins_current": calibration_bins(test, current_probabilities),
        },
        "diagnostic_examples": diagnostics,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
