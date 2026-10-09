"""Canonical, no-lookahead data products for the Fenzobot system history.

The bot may publish more than one HTML report for a fixture as the market
changes.  This module deliberately never uses those HTML files as analytical
rows.  The immutable first pre-match snapshot is the single observation for a
match, so a repeated report cannot inflate any learning metric.

Historical WTA aggregates are built exclusively from the locally cached
tennis-data.co.uk files.  They are labelled WTA / reference-line evidence and
are not PAPER results or bookmaker handicap settlement.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 6

# Rankings only surface sufficiently sized samples.  They are descriptive
# study aids, not betting recommendations or a substitute for the report's
# match-specific validation.
RANKING_MIN_SAMPLES = {
    "operational_fenzobot": 10,
    "wta_moneyline": 20,
    "wta_handicap": 20,
    "wta_recovery": 10,
    "wta_deciding_set": 10,
    "wta_tiebreak": 10,
}
RANKING_ACTIVE_WINDOW_DAYS = 365
ODDS_BANDS = (
    (1.01, 1.20, "1.01–1.20"),
    (1.21, 1.30, "1.21–1.30"),
    (1.31, 1.40, "1.31–1.40"),
    (1.41, 1.50, "1.41–1.50"),
    (1.51, 1.60, "1.51–1.60"),
    (1.61, 1.75, "1.61–1.75"),
    (1.76, 2.00, "1.76–2.00"),
    (2.01, 2.30, "2.01–2.30"),
    (2.31, 2.80, "2.31–2.80"),
    (2.81, 3.30, "2.81–3.30"),
    (3.31, math.inf, "3.31+"),
)

# Estas faixas descrevem a intensidade com que um fator entrou na decisão
# naquele snapshot. Não são novos pesos nem gatilhos de aposta: existem apenas
# para permitir auditar se uma contribuição forte se comporta de forma distinta
# de uma contribuição leve antes de qualquer calibração futura.
FACTOR_WEIGHT_BANDS = (
    (0.0, 3.0, "Leve (<3)"),
    (3.0, 6.0, "Médio (3–5,99)"),
    (6.0, math.inf, "Forte (≥6)"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(value: Any) -> str:
    return _text(value) or "9999-12-31T23:59:59+00:00"


def _match_date(value: Any) -> date | None:
    """Parse the date formats found in the locally cached WTA files."""
    raw = _text(value)
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            pass
    return None


def active_wta_players(matches: Iterable[Mapping[str, Any]]) -> set[str]:
    """Players seen in the last 12 months of the local WTA cache.

    The reference point is the newest cached result, rather than today's wall
    clock, so a temporarily delayed data refresh cannot empty the rankings.
    This filter is presentation-only: it never removes historical rows.
    """
    dated = [(match, _match_date(match.get("date"))) for match in matches]
    available_dates = [played_on for _, played_on in dated if played_on]
    if not available_dates:
        return set()
    cutoff = max(available_dates) - timedelta(days=RANKING_ACTIVE_WINDOW_DAYS)
    return {
        player
        for match, played_on in dated
        if played_on and played_on >= cutoff
        for player in (_text(match.get("winner")), _text(match.get("loser")))
        if player
    }


def odds_band(odd: Any) -> str | None:
    value = _float(odd)
    if value is None or value <= 1:
        return None
    for lower, upper, label in ODDS_BANDS:
        if lower <= value <= upper:
            return label
    return None


def fenzobot_index_band(index: Any) -> str | None:
    """Stable descriptive buckets for the selected side's Fenzobot index.

    The index is an evidence score, not a probability. These bands only make
    the settled canonical history easier to inspect; they do not tune the
    model, pricing, or PAPER eligibility.
    """
    value = _float(index)
    if value is None or value < 50 or value > 100:
        return None
    lower = int(value // 10) * 10
    if lower < 50:
        lower = 50
    if lower >= 90:
        return "90–100"
    return f"{lower}–{lower + 9}"


def snapshot_event_id(snapshot: Mapping[str, Any]) -> str:
    """Stable event identity that is defensive against provider ID reuse."""
    canonical = _text(snapshot.get("canonical_match_instance_id"))
    if canonical:
        return canonical
    player_a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
    player_b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
    players = sorted(
        value.casefold()
        for value in (
            _text(player_a.get("id")) or _text(player_a.get("name")),
            _text(player_b.get("id")) or _text(player_b.get("name")),
        )
        if value
    )
    start_day = _text(snapshot.get("commence_time_utc"))[:10]
    return "|".join((
        _text(snapshot.get("tour")).casefold(),
        _text(snapshot.get("match_id") or snapshot.get("key")),
        start_day,
        ";".join(players),
    ))


def canonical_snapshots(snapshots: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the earliest immutable observation per event, with no overwrite."""
    selected: dict[str, dict[str, Any]] = {}
    raw_count = 0
    for raw in snapshots:
        if not isinstance(raw, Mapping):
            continue
        raw_count += 1
        snapshot = dict(raw)
        event_id = snapshot_event_id(snapshot)
        previous = selected.get(event_id)
        if previous is None or _timestamp(snapshot.get("analyzed_at_utc")) < _timestamp(previous.get("analyzed_at_utc")):
            selected[event_id] = snapshot
    ordered = sorted(selected.values(), key=lambda item: (_timestamp(item.get("analyzed_at_utc")), snapshot_event_id(item)))
    return ordered, raw_count - len(ordered)


def _role(odd: float | None, opponent_odd: float | None) -> str:
    if odd is None or opponent_odd is None:
        return "indisponível"
    if odd < opponent_odd:
        return "favorito"
    if odd > opponent_odd:
        return "underdog"
    return "equilibrado"


def _reference_lines_bo3(favourite_odd: float) -> tuple[float, ...]:
    """Internal BO3 reference zones, never asserted as bookmaker lines."""
    if favourite_odd < 1.30:
        return (-4.5, -5.0)
    if favourite_odd < 1.40:
        return (-4.0, -4.5)
    if favourite_odd < 1.51:
        return (-3.0, -3.5)
    if favourite_odd < 1.61:
        return (-1.5, -2.5)
    if favourite_odd < 1.75:
        return (-1.0, -1.5)
    return ()


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _break_even_pct(average_odd: float | None) -> float | None:
    """Taxa teórica necessária para não perder com odds decimais médias.

    Isto não é ROI: usa apenas a odd média dos snapshots canónicos e não
    incorpora stake, limites, vigor variável ou execução numa casa específica.
    """
    if average_odd is None or average_odd <= 1:
        return None
    return round(100 / average_odd, 1)


def _aggregate_player_rows(rows: Iterable[tuple[str, str, str, bool]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for player, band, role, won in rows:
        if not band:
            continue
        bucket = grouped[(player, band, role)]
        bucket["matches"] += 1
        bucket["wins"] += int(won)
    return [
        {
            "player": player, "odds_band": band, "role": role,
            "matches": value["matches"], "wins": value["wins"],
            "losses": value["matches"] - value["wins"], "win_pct": _pct(value["wins"], value["matches"]),
        }
        for (player, band, role), value in sorted(grouped.items(), key=lambda item: (-item[1]["matches"], item[0]))
    ]


def _aggregate_fenzobot_band_rows(rows: Iterable[tuple[str, float, bool]]) -> list[dict[str, Any]]:
    """One canonical Fenzobot row per odds band, with break-even context."""
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"matches": 0, "wins": 0, "odds": []})
    for band, odd, won in rows:
        if not band or odd <= 1:
            continue
        grouped[band]["matches"] += 1
        grouped[band]["wins"] += int(won)
        grouped[band]["odds"].append(odd)
    return [
        {
            "odds_band": band, "matches": values["matches"], "wins": values["wins"],
            "losses": values["matches"] - values["wins"],
            "win_pct": _pct(values["wins"], values["matches"]),
            "average_odd": round(sum(values["odds"]) / len(values["odds"]), 3),
            "break_even_pct": _break_even_pct(sum(values["odds"]) / len(values["odds"])),
            "margin_vs_break_even_pp": round(
                (_pct(values["wins"], values["matches"]) or 0)
                - (_break_even_pct(sum(values["odds"]) / len(values["odds"])) or 0),
                1,
            ),
        }
        for band, values in sorted(grouped.items(), key=lambda item: _odds_band_order(item[0]))
    ]


def _aggregate_index_rows(rows: Iterable[tuple[str, bool]]) -> list[dict[str, Any]]:
    """One settled observational row per evidence-index band."""
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for band, won in rows:
        if not band:
            continue
        grouped[band]["matches"] += 1
        grouped[band]["wins"] += int(won)
    return [
        {
            "index_band": band,
            "matches": values["matches"],
            "wins": values["wins"],
            "losses": values["matches"] - values["wins"],
            "win_pct": _pct(values["wins"], values["matches"]),
        }
        for band, values in sorted(grouped.items(), key=lambda item: _index_band_order(item[0]))
    ]


def _aggregate_index_odds_rows(rows: Iterable[tuple[str, str, float, bool]]) -> list[dict[str, Any]]:
    """Cross Fenzobot evidence band with odds band without tuning the model."""
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"matches": 0, "wins": 0, "odds": []}
    )
    for index_band, band, odd, won in rows:
        if not index_band or not band or odd <= 1:
            continue
        item = grouped[(index_band, band)]
        item["matches"] += 1
        item["wins"] += int(won)
        item["odds"].append(odd)
    result = []
    for (index_band, band), values in sorted(
        grouped.items(), key=lambda item: (_index_band_order(item[0][0]), _odds_band_order(item[0][1]))
    ):
        average = round(sum(values["odds"]) / len(values["odds"]), 3)
        win_pct = _pct(values["wins"], values["matches"])
        break_even = _break_even_pct(average)
        result.append({
            "index_band": index_band, "odds_band": band, "matches": values["matches"],
            "wins": values["wins"], "losses": values["matches"] - values["wins"],
            "win_pct": win_pct, "average_odd": average, "break_even_pct": break_even,
            "margin_vs_break_even_pp": round((win_pct or 0) - (break_even or 0), 1),
        })
    return result


def _aggregate_player_overall(rows: Iterable[tuple[str, str, str, bool]]) -> list[dict[str, Any]]:
    """One observational row per player/role, used only for the shortlist."""
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for player, _band, role, won in rows:
        if not player:
            continue
        grouped[(player, role)]["matches"] += 1
        grouped[(player, role)]["wins"] += int(won)
    return [
        {"player": player, "role": role, "matches": value["matches"], "wins": value["wins"], "losses": value["matches"] - value["wins"], "win_pct": _pct(value["wins"], value["matches"])}
        for (player, role), value in sorted(grouped.items(), key=lambda item: (-item[1]["matches"], item[0]))
    ]


def _odds_band_order(band: str) -> tuple[float, str]:
    match = re.match(r"(\d+(?:\.\d+)?)", band or "")
    return (float(match.group(1)) if match else float("inf"), band)


def _index_band_order(band: str) -> tuple[float, str]:
    match = re.match(r"(\d+)", band or "")
    return (float(match.group(1)) if match else float("inf"), band)


def _ranking_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    category: str,
    metric: str,
    sample: str,
    minimum: int,
    label_fields: tuple[str, ...] = ("player",),
    active_players: set[str] | None = None,
    bottom_minimum_metric: float | None = None,
    empty_strongest_message: str = "Sem amostras suficientes",
    empty_weakest_message: str = "Sem amostras suficientes",
    bottom_title: str = "Bottom 10",
    metric_label: str = "% acerto",
) -> dict[str, Any]:
    """Return the strongest and weakest observations with enough evidence."""
    eligible = []
    for row in rows:
        count, value = _int(row.get(sample)), _float(row.get(metric))
        if count is None or count < minimum or value is None:
            continue
        player = _text(row.get("player"))
        if active_players is not None and player not in active_players:
            continue
        labels = [str(row.get(field, "")).strip() for field in label_fields]
        eligible.append({
            "category": category,
            "label": " · ".join(label for label in labels if label),
            "sample": count,
            "metric_pct": value,
        })
    strongest = sorted(eligible, key=lambda row: (-row["metric_pct"], -row["sample"], row["label"]))[:10]
    weakest_candidates = (
        [row for row in eligible if row["metric_pct"] >= bottom_minimum_metric]
        if bottom_minimum_metric is not None else eligible
    )
    weakest = sorted(weakest_candidates, key=lambda row: (row["metric_pct"], -row["sample"], row["label"]))[:10]
    return {
        "minimum_sample": minimum,
        "strongest": strongest,
        "weakest": weakest,
        "empty_strongest_message": empty_strongest_message,
        "empty_weakest_message": empty_weakest_message,
        "bottom_title": bottom_title,
        "metric_label": metric_label,
    }


def build_rankings(
    operational: Mapping[str, Any],
    historical_wta: Mapping[str, Any],
    *,
    active_players: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Stable shortlists for exploration, kept separate from predictive logic."""
    return {
        "Fenzobot · acerto operacional": _ranking_rows(
            operational.get("fenzobot_player_summary", []), category="Fenzobot · acerto operacional", metric="win_pct", sample="matches",
            minimum=RANKING_MIN_SAMPLES["operational_fenzobot"], label_fields=("player", "role"),
            empty_strongest_message="Ainda não há jogador com 10 seleções Fenzobot liquidadas.",
            empty_weakest_message="Ainda não há jogador com 10 seleções Fenzobot liquidadas.",
        ),
        "WTA ativa · vitória Moneyline": _ranking_rows(
            historical_wta.get("player_odds", []), category="WTA · vitória Moneyline", metric="win_pct", sample="matches",
            minimum=RANKING_MIN_SAMPLES["wta_moneyline"], label_fields=("player", "odds_band", "role"), active_players=active_players,
        ),
        "WTA ativa · cobertura handicap interno": _ranking_rows(
            historical_wta.get("handicap_reference", []), category="WTA · cobertura handicap interno", metric="cover_pct", sample="matches",
            minimum=RANKING_MIN_SAMPLES["wta_handicap"], label_fields=("player", "role", "reference_line"), active_players=active_players,
            metric_label="% cobre · linha de referência",
        ),
        "WTA ativa · recuperação após 1.º set": _ranking_rows(
            historical_wta.get("set1_recovery", []), category="WTA · recuperação após 1.º set", metric="recovery_pct", sample="lost_first",
            minimum=RANKING_MIN_SAMPLES["wta_recovery"], label_fields=("player",), active_players=active_players,
            bottom_minimum_metric=0.1,
            empty_weakest_message="Sem recuperações positivas com amostra suficiente.",
            bottom_title="Bottom 10 (>0%)",
        ),
        "WTA ativa · set decisivo": _ranking_rows(
            historical_wta.get("deciding_set", []), category="WTA · set decisivo", metric="win_pct", sample="matches",
            minimum=RANKING_MIN_SAMPLES["wta_deciding_set"], label_fields=("player",), active_players=active_players,
        ),
        "WTA ativa · tiebreak": _ranking_rows(
            historical_wta.get("tiebreak", []), category="WTA · tiebreak", metric="win_pct", sample="matches",
            minimum=RANKING_MIN_SAMPLES["wta_tiebreak"], label_fields=("player",), active_players=active_players,
        ),
    }


def snapshot_performance(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Outcome metrics from canonical Fenzobot observations only."""
    player_rows: list[tuple[str, str, str, bool]] = []
    model_rows: list[tuple[str, str, str, bool]] = []
    model_index_rows: list[tuple[str, bool]] = []
    model_band_rows: list[tuple[str, float, bool]] = []
    model_index_odds_rows: list[tuple[str, str, float, bool]] = []
    model_by_tour: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: {"rows": [], "index_rows": [], "band_rows": [], "index_odds_rows": []}
    )
    event_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
        b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
        name_a, name_b = _text(a.get("name")), _text(b.get("name"))
        odds = snapshot.get("market_odds_decimal") if isinstance(snapshot.get("market_odds_decimal"), Mapping) else {}
        odd_a, odd_b = _float(odds.get(name_a)), _float(odds.get(name_b))
        outcome = snapshot.get("outcome") if isinstance(snapshot.get("outcome"), Mapping) else {}
        winner = _text(outcome.get("winner_side"))
        settled = winner in {"a", "b"}
        for name, own, other, side in ((name_a, odd_a, odd_b, "a"), (name_b, odd_b, odd_a, "b")):
            if not name or not settled:
                continue
            player_rows.append((name, odds_band(own) or "sem faixa", _role(own, other), winner == side))
        divergence = ((snapshot.get("metrics") or {}).get("divergencia") or {}) if isinstance(snapshot.get("metrics"), Mapping) else {}
        model_side = _text(divergence.get("indice_favorece"))
        model_index = None
        model_index_band = None
        if settled and model_side in {name_a, name_b}:
            own = odd_a if model_side == name_a else odd_b
            other = odd_b if model_side == name_a else odd_a
            selected_side = "a" if model_side == name_a else "b"
            model_won = winner == selected_side
            band = odds_band(own)
            selected = (model_side, band or "sem faixa", _role(own, other), model_won)
            model_rows.append(selected)
            model_index = _float(divergence.get(f"indice_evidencia_{selected_side}"))
            model_index_band = fenzobot_index_band(model_index)
            tour = _text(snapshot.get("tour")).upper() or "OUTROS"
            model_by_tour[tour]["rows"].append(selected)
            if model_index_band:
                model_index_rows.append((model_index_band, model_won))
                model_by_tour[tour]["index_rows"].append((model_index_band, model_won))
            if band and own is not None and own > 1:
                model_band_rows.append((band, own, model_won))
                model_by_tour[tour]["band_rows"].append((band, own, model_won))
                if model_index_band:
                    model_index_odds_rows.append((model_index_band, band, own, model_won))
                    model_by_tour[tour]["index_odds_rows"].append((model_index_band, band, own, model_won))
        event_rows.append({
            "event_id": snapshot_event_id(snapshot), "snapshot_key": snapshot.get("key"),
            "analyzed_at_utc": snapshot.get("analyzed_at_utc"), "commence_time_utc": snapshot.get("commence_time_utc"),
            "tour": _text(snapshot.get("tour")).upper(), "tournament": snapshot.get("tournament"),
            "player_a": name_a, "player_b": name_b, "odd_a": odd_a, "odd_b": odd_b,
            "winner_side": winner or None, "result": outcome.get("result"),
            "fenzobot_side": model_side or None,
            "fenzobot_index": model_index,
            "fenzobot_index_band": model_index_band,
        })
    def operational_series(rows: Mapping[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
        fenzobot_odds = _aggregate_player_rows(rows["rows"])
        return {
            "fenzobot_odds": fenzobot_odds,
            "fenzobot_player_summary": _aggregate_player_overall(rows["rows"]),
            "fenzobot_band_summary": _aggregate_fenzobot_band_rows(rows["band_rows"]),
            "fenzobot_index_band_summary": _aggregate_index_rows(rows["index_rows"]),
            "fenzobot_index_odds_summary": _aggregate_index_odds_rows(rows["index_odds_rows"]),
        }
    all_rows = {
        "rows": model_rows, "index_rows": model_index_rows,
        "band_rows": model_band_rows, "index_odds_rows": model_index_odds_rows,
    }
    series = operational_series(all_rows)
    return {
        "event_rows": event_rows,
        "player_odds": _aggregate_player_rows(player_rows),
        **series,
        "by_tour": {tour: operational_series(rows) for tour, rows in sorted(model_by_tour.items())},
    }


def _factor_weight_band(weight: float) -> str:
    for lower, upper, label in FACTOR_WEIGHT_BANDS:
        if lower <= weight < upper:
            return label
    return FACTOR_WEIGHT_BANDS[-1][2]


def _normalised_market_probability(own_odd: float | None, opponent_odd: float | None) -> float | None:
    """Return the two-way market probability after removing the simple margin.

    This is intentionally an observational comparator, rather than a pricing
    model: it answers whether a factor's indicated side won more often than
    the contemporaneous two-way market expected in the canonical snapshot.
    """
    if own_odd is None or opponent_odd is None or own_odd <= 1 or opponent_odd <= 1:
        return None
    own_implied, opponent_implied = 1 / own_odd, 1 / opponent_odd
    return own_implied / (own_implied + opponent_implied)


def factor_attribution_analysis(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Audit each active factor against settled canonical outcomes.

    The unit is one factor direction in one canonical match.  A factor is
    considered active only where it supplied a directional impact (``a`` or
    ``b``) and a positive effective weight.  The result deliberately keeps
    the all-tour, ATP and WTA universes separate and compares each factor to
    the no-vig two-way expectation available at the time of the snapshot.

    It is not used by the model, PAPER eligibility or pricing.  Its purpose is
    to make future *small* calibration changes evidence-led rather than based
    on raw win rate (which is biased toward favourites).
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "seen": 0, "available": 0, "active": 0, "wins": 0,
            "weight_sum": 0.0, "correct_weight_sum": 0.0,
            "odds": [], "market_expected": [],
        }
    )
    grouped_by_weight: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "matches": 0, "wins": 0, "weight_sum": 0.0,
            "odds": [], "market_expected": [],
        }
    )

    for snapshot in snapshots:
        outcome = snapshot.get("outcome") if isinstance(snapshot.get("outcome"), Mapping) else {}
        winner = _text(outcome.get("winner_side"))
        if winner not in {"a", "b"}:
            continue
        metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), Mapping) else {}
        divergence = metrics.get("divergencia") if isinstance(metrics.get("divergencia"), Mapping) else {}
        statuses = divergence.get("fatores_status") if isinstance(divergence.get("fatores_status"), Mapping) else {}
        if not statuses:
            continue
        player_a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
        player_b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
        name_a, name_b = _text(player_a.get("name")), _text(player_b.get("name"))
        odds = snapshot.get("market_odds_decimal") if isinstance(snapshot.get("market_odds_decimal"), Mapping) else {}
        odd_a, odd_b = _float(odds.get(name_a)), _float(odds.get(name_b))
        tour = _text(snapshot.get("tour")).upper() or "OUTROS"

        for factor, raw_status in statuses.items():
            if not isinstance(raw_status, Mapping):
                continue
            factor_key = _text(factor)
            if not factor_key:
                continue
            scopes = ("GLOBAL", tour)
            for scope in scopes:
                item = grouped[(scope, factor_key)]
                item["seen"] += 1
                item["available"] += int(bool(raw_status.get("disponivel")))

            direction = _text(raw_status.get("direcao_impacto")).casefold()
            weight = _float(raw_status.get("peso_efetivo")) or 0.0
            if direction not in {"a", "b"} or weight <= 0:
                continue
            won = winner == direction
            own_odd, opponent_odd = (odd_a, odd_b) if direction == "a" else (odd_b, odd_a)
            expected = _normalised_market_probability(own_odd, opponent_odd)
            band = _factor_weight_band(weight)
            for scope in scopes:
                item = grouped[(scope, factor_key)]
                item["active"] += 1
                item["wins"] += int(won)
                item["weight_sum"] += weight
                item["correct_weight_sum"] += weight if won else 0.0
                if own_odd is not None:
                    item["odds"].append(own_odd)
                if expected is not None:
                    item["market_expected"].append(expected)

                by_weight = grouped_by_weight[(scope, factor_key, band)]
                by_weight["matches"] += 1
                by_weight["wins"] += int(won)
                by_weight["weight_sum"] += weight
                if own_odd is not None:
                    by_weight["odds"].append(own_odd)
                if expected is not None:
                    by_weight["market_expected"].append(expected)

    scope_order = {"GLOBAL": 0, "ATP": 1, "WTA": 2}
    summary_rows: list[dict[str, Any]] = []
    for (scope, factor), values in sorted(grouped.items(), key=lambda item: (scope_order.get(item[0][0], 9), item[0][0], item[0][1])):
        active = values["active"]
        wins = values["wins"]
        expected_values = values["market_expected"]
        hit_pct = _pct(wins, active)
        expected_pct = round(100 * sum(expected_values) / len(expected_values), 1) if expected_values else None
        summary_rows.append({
            "scope": scope,
            "factor": factor,
            "seen_snapshots": values["seen"],
            "available_snapshots": values["available"],
            "active_matches": active,
            "coverage_pct": _pct(active, values["seen"]),
            "wins": wins,
            "losses": active - wins,
            "hit_pct": hit_pct,
            "weighted_hit_pct": round(100 * values["correct_weight_sum"] / values["weight_sum"], 1) if values["weight_sum"] else None,
            "average_effective_weight": round(values["weight_sum"] / active, 3) if active else None,
            "average_odd": round(sum(values["odds"]) / len(values["odds"]), 3) if values["odds"] else None,
            "market_expected_pct": expected_pct,
            "market_residual_pp": round((hit_pct or 0) - expected_pct, 1) if hit_pct is not None and expected_pct is not None else None,
        })

    weight_order = {label: index for index, (_, _, label) in enumerate(FACTOR_WEIGHT_BANDS)}
    weight_rows: list[dict[str, Any]] = []
    for (scope, factor, band), values in sorted(
        grouped_by_weight.items(),
        key=lambda item: (scope_order.get(item[0][0], 9), item[0][0], item[0][1], weight_order.get(item[0][2], 99)),
    ):
        matches, wins = values["matches"], values["wins"]
        expected_values = values["market_expected"]
        hit_pct = _pct(wins, matches)
        expected_pct = round(100 * sum(expected_values) / len(expected_values), 1) if expected_values else None
        weight_rows.append({
            "scope": scope,
            "factor": factor,
            "weight_band": band,
            "matches": matches,
            "wins": wins,
            "losses": matches - wins,
            "hit_pct": hit_pct,
            "average_effective_weight": round(values["weight_sum"] / matches, 3) if matches else None,
            "average_odd": round(sum(values["odds"]) / len(values["odds"]), 3) if values["odds"] else None,
            "market_expected_pct": expected_pct,
            "market_residual_pp": round((hit_pct or 0) - expected_pct, 1) if hit_pct is not None and expected_pct is not None else None,
        })
    return {"summary": summary_rows, "by_weight_band": weight_rows}


def _int(value: Any) -> int | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(parsed) if math.isfinite(parsed) and parsed.is_integer() else None


def load_local_wta_history(cache_dir: Path) -> list[dict[str, Any]]:
    """Read the WTA raw files already present locally; never fetches data."""
    rows: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("wta_tdcouk_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if _text(row.get("Comment")).casefold() not in {"", "completed"}:
                    continue
                winner, loser = _text(row.get("winner_name")), _text(row.get("loser_name"))
                if not winner or not loser:
                    continue
                w1, l1, w2, l2, w3, l3 = (_int(row.get(key)) for key in ("W1", "L1", "W2", "L2", "W3", "L3"))
                if None in {w1, l1, w2, l2}:
                    continue
                odds_w = _float(row.get("AvgW")) or _float(row.get("PSW")) or _float(row.get("B365W"))
                odds_l = _float(row.get("AvgL")) or _float(row.get("PSL")) or _float(row.get("B365L"))
                rows.append({
                    "date": _text(row.get("tourney_date")), "winner": winner, "loser": loser,
                    "winner_odd": odds_w, "loser_odd": odds_l,
                    "winner_games": w1 + w2 + (w3 or 0), "loser_games": l1 + l2 + (l3 or 0),
                    "winner_lost_first": w1 < l1, "deciding_set": w3 is not None and l3 is not None,
                    "winner_tiebreak": max(w1, l1) == 7 and abs(w1 - l1) == 1 or max(w2, l2) == 7 and abs(w2 - l2) == 1 or (w3 is not None and l3 is not None and max(w3, l3) == 7 and abs(w3 - l3) == 1),
                })
    return rows


def historical_wta_analytics(matches: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    player_rows: list[tuple[str, str, str, bool]] = []
    handicap: dict[tuple[str, str, float], dict[str, int]] = defaultdict(lambda: {"matches": 0, "covers": 0, "pushes": 0, "fails": 0})
    recovery: dict[str, dict[str, int]] = defaultdict(lambda: {"lost_first": 0, "recovered": 0})
    deciding: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    tiebreak: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for match in matches:
        winner, loser = _text(match.get("winner")), _text(match.get("loser"))
        odd_w, odd_l = _float(match.get("winner_odd")), _float(match.get("loser_odd"))
        if odd_w and odd_l:
            player_rows.extend(((winner, odds_band(odd_w) or "sem faixa", _role(odd_w, odd_l), True), (loser, odds_band(odd_l) or "sem faixa", _role(odd_l, odd_w), False)))
            favourite, favourite_odd = (winner, odd_w) if odd_w < odd_l else (loser, odd_l)
            fav_diff = (int(match["winner_games"]) - int(match["loser_games"])) * (1 if favourite == winner else -1)
            for line in _reference_lines_bo3(favourite_odd):
                for player, applied_line, games_diff, role in ((favourite, line, fav_diff, "favorito"), (loser if favourite == winner else winner, -line, -fav_diff, "underdog")):
                    item = handicap[(player, role, applied_line)]
                    item["matches"] += 1
                    total = games_diff + applied_line
                    if total > 0:
                        item["covers"] += 1
                    elif total == 0:
                        item["pushes"] += 1
                    else:
                        item["fails"] += 1
        if match.get("winner_lost_first"):
            recovery[winner]["lost_first"] += 1
            recovery[winner]["recovered"] += 1
        else:
            # If the eventual winner won set one, the loser is the player who
            # lost it first and did not recover.  Keeping this denominator is
            # essential: otherwise every player's recovery rate is inflated.
            recovery[loser]["lost_first"] += 1
        if match.get("deciding_set"):
            deciding[winner]["matches"] += 1; deciding[winner]["wins"] += 1
            deciding[loser]["matches"] += 1
        if match.get("winner_tiebreak"):
            tiebreak[winner]["matches"] += 1; tiebreak[winner]["wins"] += 1
            tiebreak[loser]["matches"] += 1
    handicap_rows = []
    for (player, role, line), value in sorted(handicap.items(), key=lambda item: (-item[1]["matches"], item[0])):
        handicap_rows.append({"player": player, "role": role, "reference_line": line, **value, "cover_pct": _pct(value["covers"], value["matches"])})
    recovery_rows = [{"player": player, **value, "recovery_pct": _pct(value["recovered"], value["lost_first"])} for player, value in sorted(recovery.items(), key=lambda item: (-item[1]["lost_first"], item[0]))]
    deciding_rows = [{"player": player, **value, "win_pct": _pct(value["wins"], value["matches"])} for player, value in sorted(deciding.items(), key=lambda item: (-item[1]["matches"], item[0]))]
    tiebreak_rows = [{"player": player, **value, "win_pct": _pct(value["wins"], value["matches"])} for player, value in sorted(tiebreak.items(), key=lambda item: (-item[1]["matches"], item[0]))]
    return {"player_odds": _aggregate_player_rows(player_rows), "handicap_reference": handicap_rows, "set1_recovery": recovery_rows, "deciding_set": deciding_rows, "tiebreak": tiebreak_rows}


def build_system_history(
    snapshot_document: Mapping[str, Any],
    local_wta_matches: Iterable[Mapping[str, Any]],
    report_files: Iterable[str] = (),
) -> dict[str, Any]:
    local_wta_matches = list(local_wta_matches)
    report_registry = []
    for name in sorted({_text(item) for item in report_files if _text(item)}):
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", name)
        report_registry.append({"report_file": name, "report_date": match.group(1) if match else None})
    raw = snapshot_document.get("snapshots") if isinstance(snapshot_document.get("snapshots"), list) else []
    canonical, removed = canonical_snapshots(raw)
    operational = snapshot_performance(canonical)
    operational["factor_attribution"] = factor_attribution_analysis(canonical)
    history = historical_wta_analytics(local_wta_matches)
    rankings = build_rankings(operational, history, active_players=active_wta_players(local_wta_matches))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "methodology": {
            "canonical_snapshot_rule": "first_valid_pre_match_snapshot_per_event",
            "raw_report_html_excluded_from_metrics": True,
            "historical_wta_source": "local tennis-data.co.uk cache only",
            "historical_atp_source": "unavailable; ATP sheets use canonical Fenzobot snapshots only",
            "handicap_reference": "BO3 internal reference line; not a bookmaker handicap settlement",
            "fenzobot_index_learning": "settled canonical observations grouped by the selected side's 50–100 evidence-index band; descriptive only, not a probability or model tuning",
            "factor_attribution": "active directional factor contributions compared with settled canonical outcomes and no-vig two-way market expectation; descriptive audit only, not automatic model tuning",
            "break_even": "theoretical 1 / average decimal odds per canonical snapshot band; not ROI, stake, vig or 22Bet execution",
            "workbook_layout_version": 2,
        },
        "summary": {
            "raw_snapshots": len(raw), "canonical_snapshots": len(canonical), "duplicate_snapshots_excluded": removed,
            "settled_canonical_snapshots": sum(1 for item in canonical if _text((item.get("outcome") or {}).get("winner_side")) in {"a", "b"}),
            "settled_fenzobot_index_observations": sum(item["matches"] for item in operational["fenzobot_index_band_summary"]),
            "historical_wta_matches": len(local_wta_matches),
            "raw_report_html_versions": len(report_registry),
        },
        "operational": operational,
        "historical_wta": history,
        "rankings": rankings,
        "report_registry": report_registry,
    }
    canonical_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["input_fingerprint_sha256"] = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return payload


def write_if_changed(payload: Mapping[str, Any], target: Path) -> bool:
    """Avoid commits and workbook rewrites when source data did not change."""
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        old = {}
    if old.get("input_fingerprint_sha256") == payload.get("input_fingerprint_sha256"):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True
