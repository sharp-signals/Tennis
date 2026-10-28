"""Audita e calibra um prior estrutural independente para o pricing.

O mercado nunca é preditor. A base usa a diferença logarítmica de pontos de
ranking observados antes do jogo; o sinal dos fatores entra como ajuste
adicional. A avaliação é cronológica para impedir que o bloco de validação
participe no ajuste dos coeficientes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from calibrate_market_residual import DEFAULT_SNAPSHOTS

ROOT = Path(__file__).resolve().parents[1]

FAMILY_NAMES = (
    "forca_base",
    "matchup",
    "superficie",
    "resiliencia",
    "ranking_fam",
    "contexto",
    "historial",
)
FAMILY_CAPS = {
    "forca_base": 10.0,
    "matchup": 18.0,
    "superficie": 16.0,
    "resiliencia": 19.0,
    "ranking_fam": 9.0,
    "contexto": 8.0,
    "historial": 6.0,
}
FACTOR_FAMILY = {
    factor: family
    for family, factors in {
        "forca_base": {"servico_recente", "servico_carreira", "forma_recente"},
        "matchup": {"matchup_maos", "h2h", "h2h_piso"},
        "superficie": {"piso", "velocidade_piso", "indoor_outdoor"},
        "resiliencia": {"recuperacao_sets", "tiebreak", "comeback_set1", "pressao_ronda"},
        "ranking_fam": {"ranking", "ranking_evolucao"},
        "contexto": {"fadiga", "lesao", "meteo", "mudanca_piso"},
        "historial": {"historico_torneio"},
    }.items()
    for factor in factors
}
BASE_FEATURE_NAMES = ("rank_log_points", "rank_log_position_ratio")
FEATURE_NAMES = BASE_FEATURE_NAMES + FAMILY_NAMES
FACTOR_WEIGHTS = {
    "h2h_piso": 12.0, "piso": 8.0, "velocidade_piso": 10.0,
    "recuperacao_sets": 9.0, "qualidade_vitorias": 8.0,
    "matchup_maos": 8.0, "forma_recente": 7.0, "sazonal": 6.0,
    "h2h": 6.0, "indoor_outdoor": 6.0, "ranking": 5.0,
    "ranking_evolucao": 6.25, "lesao": 5.0, "tiebreak": 5.0,
    "pressao_ronda": 6.0, "nivel_adversario": 7.0,
    "historico_torneio": 6.0, "comeback_set1": 7.0, "fadiga": 3.75,
    "mudanca_piso": 5.0, "servico_recente": 5.0,
    "servico_carreira": 3.25, "meteo": 1.0,
}
FACTOR_NAMES = tuple(FACTOR_WEIGHTS)
INDIVIDUAL_FEATURE_NAMES = BASE_FEATURE_NAMES + FACTOR_NAMES


@dataclass(frozen=True)
class Row:
    key: str
    player_a: str
    player_b: str
    surface: str
    analyzed_at: datetime
    segment: str
    rank_log_ratio: float
    rank_log_position_ratio: float
    signed_strength: float
    factor_predictor: float
    family_predictors: tuple[float, ...]
    individual_predictors: tuple[float, ...]
    target_a: float
    market_probability_a: float | None


def _dt(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _market_probability(snapshot: Mapping) -> float | None:
    odds = snapshot.get("market_odds_decimal")
    if not isinstance(odds, Mapping):
        return None
    names = []
    for value in (snapshot.get("player_a"), snapshot.get("player_b")):
        names.append(str(value.get("name") if isinstance(value, Mapping) else value or ""))
    found = []
    for side, name in zip(("a", "b"), names):
        odd = _number(odds.get(f"player_{side}"))
        if odd is None:
            for key, value in odds.items():
                if str(key).casefold() == name.casefold():
                    odd = _number(value)
                    break
        found.append(odd if odd and odd > 1 else None)
    if any(value is None for value in found):
        return None
    raw_a, raw_b = 1.0 / found[0], 1.0 / found[1]
    return raw_a / (raw_a + raw_b)


def _segment(snapshot: Mapping) -> str | None:
    tier = str(snapshot.get("tier") or "").casefold()
    tour = str(snapshot.get("tour") or "").casefold()
    if "challenger" in tier:
        return "challenger"
    return tour if tour in {"atp", "wta"} else None


def _family_predictors(divergence: Mapping) -> tuple[float, ...]:
    """Preserva a direção/massa de cada família em vez de esmagar tudo num índice."""
    totals = {name: 0.0 for name in FAMILY_NAMES}
    statuses = divergence.get("fatores_status")
    if not isinstance(statuses, Mapping):
        return tuple(totals[name] for name in FAMILY_NAMES)
    for factor, status in statuses.items():
        if not isinstance(status, Mapping):
            continue
        direction = str(status.get("direcao_impacto") or "").casefold()
        if direction not in {"a", "b"}:
            continue
        family = str(status.get("familia_peso") or FACTOR_FAMILY.get(str(factor), ""))
        if family not in totals:
            continue
        weight = _number(status.get("peso_efetivo"))
        if weight is None or weight <= 0:
            continue
        totals[family] += weight if direction == "a" else -weight
    return tuple(
        max(-1.0, min(1.0, totals[name] / FAMILY_CAPS[name]))
        for name in FAMILY_NAMES
    )


def _individual_predictors(divergence: Mapping) -> tuple[float, ...]:
    statuses = divergence.get("fatores_status")
    if not isinstance(statuses, Mapping):
        return tuple(0.0 for _ in FACTOR_NAMES)
    values = []
    for factor in FACTOR_NAMES:
        status = statuses.get(factor)
        if not isinstance(status, Mapping):
            values.append(0.0)
            continue
        direction = str(status.get("direcao_impacto") or "").casefold()
        weight = _number(status.get("peso_efetivo"))
        if direction not in {"a", "b"} or weight is None or weight <= 0:
            values.append(0.0)
            continue
        signed = weight / FACTOR_WEIGHTS[factor]
        values.append(max(-1.0, min(1.0, signed if direction == "a" else -signed)))
    return tuple(values)


def load_rows(path: Path = DEFAULT_SNAPSHOTS) -> list[Row]:
    document = json.loads(path.read_text(encoding="utf-8"))
    earliest: dict[str, Mapping] = {}
    for snapshot in document.get("snapshots", []):
        if not isinstance(snapshot, Mapping):
            continue
        key = str(snapshot.get("canonical_match_instance_id") or snapshot.get("event_key") or snapshot.get("key") or "")
        analyzed_at = _dt(snapshot.get("analyzed_at_utc"))
        if not key or analyzed_at is None:
            continue
        current = earliest.get(key)
        if current is None or analyzed_at < _dt(current.get("analyzed_at_utc")):
            earliest[key] = snapshot

    rows = []
    for key, snapshot in earliest.items():
        outcome = snapshot.get("outcome")
        winner = outcome.get("winner_side") if isinstance(outcome, Mapping) else None
        analyzed_at = _dt(snapshot.get("analyzed_at_utc"))
        commence = _dt(snapshot.get("commence_time_utc"))
        segment = _segment(snapshot)
        metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), Mapping) else {}
        rank_a = metrics.get("ranking_a") if isinstance(metrics.get("ranking_a"), Mapping) else {}
        rank_b = metrics.get("ranking_b") if isinstance(metrics.get("ranking_b"), Mapping) else {}
        points_a, points_b = _number(rank_a.get("points")), _number(rank_b.get("points"))
        position_a, position_b = _number(rank_a.get("rank")), _number(rank_b.get("rank"))
        divergence = metrics.get("divergencia") if isinstance(metrics.get("divergencia"), Mapping) else {}
        index_a = _number(divergence.get("indice_evidencia_a"))
        pricing = snapshot.get("pricing") if isinstance(snapshot.get("pricing"), Mapping) else {}
        quality = _number(pricing.get("quality_score"))
        if quality is None:
            quality = 1.0
        if (
            winner not in {"a", "b"} or analyzed_at is None or commence is None
            or analyzed_at >= commence or segment is None or not points_a or not points_b
            or not position_a or not position_b or points_a <= 0 or points_b <= 0
            or position_a <= 0 or position_b <= 0 or index_a is None
        ):
            continue
        rows.append(Row(
            key=key,
            player_a=str(snapshot.get("player_a", {}).get("name") if isinstance(snapshot.get("player_a"), Mapping) else snapshot.get("player_a") or ""),
            player_b=str(snapshot.get("player_b", {}).get("name") if isinstance(snapshot.get("player_b"), Mapping) else snapshot.get("player_b") or ""),
            surface=str(snapshot.get("surface") or "unknown"),
            analyzed_at=analyzed_at,
            segment=segment,
            rank_log_ratio=max(-4.0, min(4.0, math.log(points_a / points_b))),
            rank_log_position_ratio=max(-4.0, min(4.0, math.log(position_b / position_a))),
            signed_strength=max(-1.0, min(1.0, (index_a - 50.0) / 50.0)),
            factor_predictor=max(-1.0, min(1.0, (index_a - 50.0) / 50.0)) * max(0.0, min(1.0, quality)),
            family_predictors=_family_predictors(divergence),
            individual_predictors=_individual_predictors(divergence),
            target_a=1.0 if winner == "a" else 0.0,
            market_probability_a=_market_probability(snapshot),
        ))
    return sorted(rows, key=lambda row: (row.analyzed_at, row.key))


def _vector(row: Row) -> tuple[float, ...]:
    return (row.rank_log_ratio, row.rank_log_position_ratio) + row.family_predictors


def _individual_vector(row: Row) -> tuple[float, ...]:
    return (row.rank_log_ratio, row.rank_log_position_ratio) + row.individual_predictors


def _probability_vector(row: Row, coefficients: tuple[float, ...]) -> float:
    z = sum(coefficient * value for coefficient, value in zip(coefficients, _vector(row)))
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _probability_individual(row: Row, coefficients: tuple[float, ...]) -> float:
    z = sum(
        coefficient * value
        for coefficient, value in zip(coefficients, _individual_vector(row))
    )
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _probability_aggregate(row: Row, coefficients: tuple[float, float]) -> float:
    z = coefficients[0] * row.rank_log_ratio + coefficients[1] * row.factor_predictor
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _solve(matrix: list[list[float]], values: list[float]) -> list[float]:
    """Resolve um sistema pequeno por eliminação de Gauss com pivot parcial."""
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
            if scale == 0:
                continue
            augmented[row] = [
                current - scale * pivot_value
                for current, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def fit_aggregate(rows: Iterable[Row], *, ridge: float = 0.05) -> tuple[float, float]:
    material = list(rows)
    coefficients = [0.0, 0.0]
    for _ in range(100):
        gradient = [-ridge * coefficients[0], -ridge * coefficients[1]]
        h00 = h11 = ridge
        h01 = 0.0
        for row in material:
            p = _probability_aggregate(row, tuple(coefficients))
            error = row.target_a - p
            x0, x1 = row.rank_log_ratio, row.factor_predictor
            gradient[0] += x0 * error
            gradient[1] += x1 * error
            variance = p * (1.0 - p)
            h00 += x0 * x0 * variance
            h01 += x0 * x1 * variance
            h11 += x1 * x1 * variance
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-12:
            break
        delta0 = (h11 * gradient[0] - h01 * gradient[1]) / determinant
        delta1 = (-h01 * gradient[0] + h00 * gradient[1]) / determinant
        coefficients[0] += delta0
        coefficients[1] += delta1
        if max(abs(delta0), abs(delta1)) < 1e-10:
            break
    return tuple(coefficients)


def fit_vector(rows: Iterable[Row], *, ridge: float = 1.0) -> tuple[float, ...]:
    material = list(rows)
    size = len(FEATURE_NAMES)
    coefficients = [0.0] * size
    for _ in range(100):
        gradient = [-ridge * coefficient for coefficient in coefficients]
        hessian = [
            [ridge if row == column else 0.0 for column in range(size)]
            for row in range(size)
        ]
        for item in material:
            features = _vector(item)
            probability = _probability_vector(item, tuple(coefficients))
            error = item.target_a - probability
            variance = probability * (1.0 - probability)
            for row in range(size):
                gradient[row] += features[row] * error
                for column in range(size):
                    hessian[row][column] += features[row] * features[column] * variance
        delta = _solve(hessian, gradient)
        coefficients = [value + change for value, change in zip(coefficients, delta)]
        if max(abs(value) for value in delta) < 1e-10:
            break
    return tuple(coefficients)


def fit_individual(rows: Iterable[Row], *, ridge: float = 1.0) -> tuple[float, ...]:
    material = list(rows)
    size = len(INDIVIDUAL_FEATURE_NAMES)
    coefficients = [0.0] * size
    for _ in range(100):
        gradient = [-ridge * coefficient for coefficient in coefficients]
        hessian = [
            [ridge if row == column else 0.0 for column in range(size)]
            for row in range(size)
        ]
        for item in material:
            features = _individual_vector(item)
            probability = _probability_individual(item, tuple(coefficients))
            error = item.target_a - probability
            variance = probability * (1.0 - probability)
            for row in range(size):
                gradient[row] += features[row] * error
                for column in range(size):
                    hessian[row][column] += features[row] * features[column] * variance
        delta = _solve(hessian, gradient)
        coefficients = [value + change for value, change in zip(coefficients, delta)]
        if max(abs(value) for value in delta) < 1e-10:
            break
    return tuple(coefficients)


def score_vector(rows: Iterable[Row], coefficients: tuple[float, ...]) -> dict:
    material = list(rows)
    probabilities = [_probability_vector(row, coefficients) for row in material]
    brier = sum((p - row.target_a) ** 2 for p, row in zip(probabilities, material)) / len(material)
    log_loss = -sum(
        row.target_a * math.log(max(p, 1e-12))
        + (1.0 - row.target_a) * math.log(max(1.0 - p, 1e-12))
        for p, row in zip(probabilities, material)
    ) / len(material)
    return {"n": len(material), "brier": round(brier, 6), "log_loss": round(log_loss, 6)}


def score_aggregate(rows: Iterable[Row], coefficients: tuple[float, float]) -> dict:
    material = list(rows)
    probabilities = [_probability_aggregate(row, coefficients) for row in material]
    brier = sum((p - row.target_a) ** 2 for p, row in zip(probabilities, material)) / len(material)
    log_loss = -sum(
        row.target_a * math.log(max(p, 1e-12))
        + (1.0 - row.target_a) * math.log(max(1.0 - p, 1e-12))
        for p, row in zip(probabilities, material)
    ) / len(material)
    return {"n": len(material), "brier": round(brier, 6), "log_loss": round(log_loss, 6)}


def score_individual(rows: Iterable[Row], coefficients: tuple[float, ...]) -> dict:
    material = list(rows)
    probabilities = [_probability_individual(row, coefficients) for row in material]
    brier = sum((p - row.target_a) ** 2 for p, row in zip(probabilities, material)) / len(material)
    log_loss = -sum(
        row.target_a * math.log(max(p, 1e-12))
        + (1.0 - row.target_a) * math.log(max(1.0 - p, 1e-12))
        for p, row in zip(probabilities, material)
    ) / len(material)
    return {"n": len(material), "brier": round(brier, 6), "log_loss": round(log_loss, 6)}


def report(rows: list[Row], train_fraction: float = 0.70) -> dict:
    result = {}
    for segment in ("atp", "wta", "challenger"):
        segment_rows = [row for row in rows if row.segment == segment]
        if len(segment_rows) < 20:
            result[segment] = {"n": len(segment_rows), "status": "insufficient"}
            continue
        split = max(1, min(len(segment_rows) - 1, int(len(segment_rows) * train_fraction)))
        train, holdout = segment_rows[:split], segment_rows[split:]
        aggregate = fit_aggregate(train)
        rank_only_aggregate = (fit_aggregate(train)[0], 0.0)
        factor_only_aggregate = (0.0, fit_aggregate(train)[1])
        family = fit_vector(train)
        family_without_rank = (0.0, 0.0) + fit_vector(train)[2:]
        nested_train_end = max(1, int(len(segment_rows) * 0.60))
        nested_validation_end = max(nested_train_end + 1, int(len(segment_rows) * 0.80))
        nested_train = segment_rows[:nested_train_end]
        nested_validation = segment_rows[nested_train_end:nested_validation_end]
        nested_test = segment_rows[nested_validation_end:]
        ridge_candidates = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0)
        ridge_scores = []
        for ridge in ridge_candidates:
            candidate = fit_individual(nested_train, ridge=ridge)
            ridge_scores.append((score_individual(nested_validation, candidate)["log_loss"], ridge))
        selected_ridge = min(ridge_scores)[1]
        individual = fit_individual(segment_rows[:nested_validation_end], ridge=selected_ridge)
        market_rows = [row for row in holdout if row.market_probability_a is not None]
        market_brier = (
            sum((row.market_probability_a - row.target_a) ** 2 for row in market_rows) / len(market_rows)
            if market_rows else None
        )
        result[segment] = {
            "n": len(segment_rows), "train_n": len(train), "holdout_n": len(holdout),
            "coefficients": {
                "aggregate": {"rank_log_points": round(aggregate[0], 6), "factor_residual": round(aggregate[1], 6)},
                "family": {name: round(value, 6) for name, value in zip(FEATURE_NAMES, family)},
                "individual": {
                    "selected_ridge": selected_ridge,
                    "values": {
                        name: round(value, 6)
                        for name, value in zip(INDIVIDUAL_FEATURE_NAMES, individual)
                    },
                },
            },
            "holdout": {
                "rank_plus_aggregate": score_aggregate(holdout, aggregate),
                "rank_only": score_aggregate(holdout, rank_only_aggregate),
                "aggregate_only": score_aggregate(holdout, factor_only_aggregate),
                "rank_plus_families": score_vector(holdout, family),
                "families_only": score_vector(holdout, family_without_rank),
                "individual_nested_test": score_individual(nested_test, individual),
                "neutral": score_vector(holdout, tuple(0.0 for _ in FEATURE_NAMES)),
                "market": {"n": len(market_rows), "brier": round(market_brier, 6) if market_brier is not None else None},
            },
        }
        if segment == "atp":
            examples = []
            full_family = fit_vector(segment_rows)
            for row in segment_rows:
                names = {row.player_a.casefold(), row.player_b.casefold()}
                if names == {"tommy paul", "luciano darderi"}:
                    probability_a = _probability_vector(row, full_family)
                    examples.append({
                        "match": f"{row.player_a} vs {row.player_b}",
                        "probability_a_pct": round(probability_a * 100.0, 2),
                        "features": {
                            name: round(value, 6)
                            for name, value in zip(FEATURE_NAMES, _vector(row))
                        },
                    })
            result[segment]["diagnostic_examples"] = examples
    return result


if __name__ == "__main__":
    print(json.dumps(report(load_rows()), ensure_ascii=False, indent=2))
