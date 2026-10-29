"""Validação cronológica de um prior Elo estrutural, sem usar odds de mercado.

O Elo global e por superfície é reconstruído apenas com resultados anteriores
à data de cada snapshot. Os sinais do Fenzobot entram depois como ajuste, não
como substituto da força-base dos jogadores.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from calibrate_structural_probability import load_rows

ROOT = Path(__file__).resolve().parents[1]
ATP_FILES = sorted((ROOT / "data" / "history_cache").glob("valuebetennis_atp_*.csv.gz"))


def _name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def _surface(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        char for char in raw if not unicodedata.combining(char)
    ).casefold().strip()
    if "hard" in normalized or normalized.startswith("dur"):
        return "hard"
    if "clay" in normalized or "terre battue" in normalized:
        return "clay"
    if "grass" in normalized or "gazon" in normalized:
        return "grass"
    if "carpet" in normalized or "moquette" in normalized:
        return "carpet"
    return "unknown"


@dataclass(frozen=True)
class Match:
    played_on: date
    surface: str
    indoor: bool
    scope: str
    winner: str
    loser: str


def load_matches() -> list[Match]:
    matches = []
    for path in ATP_FILES:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    played_on = date.fromisoformat(str(row.get("date") or ""))
                except ValueError:
                    continue
                winner, loser = _name(row.get("winner_name")), _name(row.get("loser_name"))
                if not winner or not loser or not str(row.get("score") or "").strip():
                    continue
                matches.append(Match(
                    played_on=played_on,
                    surface=_surface(row.get("surface")),
                    indoor=str(row.get("indoor") or "").casefold() in {"true", "1", "yes"},
                    scope=str(row.get("_history_competition_scope") or "").casefold(),
                    winner=winner,
                    loser=loser,
                ))
    return sorted(matches, key=lambda item: (item.played_on, item.winner, item.loser))


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def elo_features(rows, matches: list[Match], *, k: float):
    matches = [match for match in matches if match.scope == "main"]
    global_ratings = defaultdict(lambda: 1500.0)
    surface_ratings = defaultdict(lambda: 1500.0)
    context_ratings = defaultdict(lambda: 1500.0)
    match_index = 0
    features = {}
    for row in sorted(rows, key=lambda item: (item.analyzed_at, item.key)):
        cutoff = row.analyzed_at.date()
        while match_index < len(matches) and matches[match_index].played_on < cutoff:
            match = matches[match_index]
            global_expected = _expected(global_ratings[match.winner], global_ratings[match.loser])
            change = k * (1.0 - global_expected)
            global_ratings[match.winner] += change
            global_ratings[match.loser] -= change
            winner_key = (match.surface, match.winner)
            loser_key = (match.surface, match.loser)
            surface_expected = _expected(surface_ratings[winner_key], surface_ratings[loser_key])
            surface_change = k * (1.0 - surface_expected)
            surface_ratings[winner_key] += surface_change
            surface_ratings[loser_key] -= surface_change
            context = (match.surface, match.indoor)
            winner_context_key = (context, match.winner)
            loser_context_key = (context, match.loser)
            context_expected = _expected(
                context_ratings[winner_context_key], context_ratings[loser_context_key]
            )
            context_change = k * (1.0 - context_expected)
            context_ratings[winner_context_key] += context_change
            context_ratings[loser_context_key] -= context_change
            match_index += 1
        player_a, player_b = _name(row.player_a), _name(row.player_b)
        surface = _surface(row.surface)
        indoor = "indoor" in str(row.surface or "").casefold()
        context = (surface, indoor)
        features[row.key] = (
            (global_ratings[player_a] - global_ratings[player_b]) * math.log(10.0) / 400.0,
            (surface_ratings[(surface, player_a)] - surface_ratings[(surface, player_b)]) * math.log(10.0) / 400.0,
            (context_ratings[(context, player_a)] - context_ratings[(context, player_b)]) * math.log(10.0) / 400.0,
            row.signed_strength,
        )
    return features


def _probability(values, coefficients):
    z = max(-20.0, min(20.0, sum(a * b for a, b in zip(values, coefficients))))
    return 1.0 / (1.0 + math.exp(-z))


def _solve(matrix, values):
    size = len(values)
    augmented = [row[:] + [value] for row, value in zip(matrix, values)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            return [0.0] * size
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            scale = augmented[row][column]
            augmented[row] = [
                current - scale * pivot_value
                for current, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def fit(rows, features, *, ridge=1.0, nonnegative=False):
    size = 4
    coefficients = [0.0] * size
    for _ in range(100):
        gradient = [-ridge * value for value in coefficients]
        hessian = [[ridge if a == b else 0.0 for b in range(size)] for a in range(size)]
        for row in rows:
            values = features[row.key]
            probability = _probability(values, coefficients)
            error = row.target_a - probability
            variance = probability * (1.0 - probability)
            for a in range(size):
                gradient[a] += values[a] * error
                for b in range(size):
                    hessian[a][b] += values[a] * values[b] * variance
        delta = _solve(hessian, gradient)
        coefficients = [value + change for value, change in zip(coefficients, delta)]
        if nonnegative:
            coefficients = [max(0.0, value) for value in coefficients]
        if max(abs(value) for value in delta) < 1e-10:
            break
    return tuple(coefficients)


def score(rows, features, coefficients):
    probabilities = [_probability(features[row.key], coefficients) for row in rows]
    return {
        "n": len(rows),
        "brier": round(sum((p - row.target_a) ** 2 for p, row in zip(probabilities, rows)) / len(rows), 6),
        "log_loss": round(-sum(
            row.target_a * math.log(max(p, 1e-12))
            + (1.0 - row.target_a) * math.log(max(1.0 - p, 1e-12))
            for p, row in zip(probabilities, rows)
        ) / len(rows), 6),
    }


def covariance(rows, features, coefficients, *, ridge=1.0):
    size = len(coefficients)
    hessian = [[ridge if a == b else 0.0 for b in range(size)] for a in range(size)]
    for row in rows:
        values = features[row.key]
        probability = _probability(values, coefficients)
        variance = probability * (1.0 - probability)
        for a in range(size):
            for b in range(size):
                hessian[a][b] += values[a] * values[b] * variance
    columns = []
    for column in range(size):
        unit = [1.0 if row == column else 0.0 for row in range(size)]
        columns.append(_solve(hessian, unit))
    return [[columns[column][row] for column in range(size)] for row in range(size)]


def main():
    rows = [row for row in load_rows() if row.segment == "atp"]
    matches = load_matches()
    main_matches = [match for match in matches if match.scope == "main"]
    train_end, validation_end = int(len(rows) * 0.60), int(len(rows) * 0.80)
    train, validation, test = rows[:train_end], rows[train_end:validation_end], rows[validation_end:]
    candidates = []
    for k in (12.0, 16.0, 20.0, 24.0, 32.0, 40.0):
        features = elo_features(rows, matches, k=k)
        coefficients = fit(train, features, ridge=1.0, nonnegative=True)
        candidates.append((score(validation, features, coefficients)["log_loss"], k))
    selected_k = min(candidates)[1]
    features = elo_features(rows, matches, k=selected_k)
    coefficients = fit(rows[:validation_end], features, ridge=1.0, nonnegative=True)
    output = {
        "history_matches_total": len(matches),
        "history_matches_atp_main_used": len(main_matches),
        "rows": len(rows),
        "selected_k": selected_k,
        "coefficients": dict(zip(("elo_global", "elo_surface", "elo_surface_context", "factor_adjustment"), coefficients)),
        "nested_test": score(test, features, coefficients),
        "nested_test_baselines": {
            "elo_global_standard": score(test, features, (1.0, 0.0, 0.0, 0.0)),
            "elo_surface_standard": score(test, features, (0.0, 1.0, 0.0, 0.0)),
            "elo_context_standard": score(test, features, (0.0, 0.0, 1.0, 0.0)),
            "elo_equal_blend": score(test, features, (1 / 3, 1 / 3, 1 / 3, 0.0)),
            "factors_only": score(test, features, (0.0, 0.0, 0.0, 1.0)),
            "elo_global_plus_factors_standard": score(
                test, features, (1.0, 0.0, 0.0, 1.0)
            ),
            "elo_blend_plus_factors_standard": score(
                test, features, (0.5, 0.25, 0.25, 1.0)
            ),
        },
        "validation_grid": [{"k": k, "log_loss": loss} for loss, k in sorted(candidates, key=lambda item: item[1])],
    }
    production_coefficients = fit(rows, features, ridge=1.0, nonnegative=True)
    output["production_fit_all_settled"] = {
        "coefficients": dict(zip(
            ("elo_global", "elo_surface", "elo_surface_context", "factor_adjustment"),
            production_coefficients,
        )),
        "covariance": covariance(rows, features, production_coefficients),
        "in_sample_diagnostic_only": score(rows, features, production_coefficients),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
