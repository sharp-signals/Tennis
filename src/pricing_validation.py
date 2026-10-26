"""Temporal, paired validation of frozen SHADOW probabilities against market."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping

from .shadow_pricing_store import first_valid_by_match_and_version


def _scores(rows: list[dict[str, float]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None}
    brier = sum((r["p"] - r["y"]) ** 2 for r in rows) / len(rows)
    logloss = -sum(r["y"] * math.log(max(1e-12, r["p"])) + (1-r["y"]) * math.log(max(1e-12, 1-r["p"])) for r in rows) / len(rows)
    return {"n": len(rows), "brier": round(brier, 6), "log_loss": round(logloss, 6)}


def _calibration(rows: list[dict[str, float]]) -> list[dict[str, Any]]:
    bins = []
    for low in (0.0, .2, .4, .6, .8):
        bucket = [r for r in rows if low <= r["p"] < low + .2 or (low == .8 and r["p"] == 1)]
        if bucket:
            bins.append({"range": f"{low:.1f}-{low+.2:.1f}", "n": len(bucket),
                         "mean_probability": round(sum(r["p"] for r in bucket)/len(bucket), 4),
                         "observed_rate": round(sum(r["y"] for r in bucket)/len(bucket), 4)})
    return bins


def _selection_metrics(sample: list[dict[str, Any]], commission: float = 0.05) -> dict[str, Any]:
    selected, pnl, equity, peak, drawdown = [], 0.0, 0.0, 0.0, 0.0
    for row in sample:
        side = row.get("candidate_side")
        if side not in ("a", "b"):
            continue
        won = row["winner"] == side
        odd = row[f"odd_{side}"]
        result = (odd - 1.0) * (1.0 - commission) if won else -1.0
        selected.append(result); pnl += result; equity += result; peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"n": len(selected), "commission_on_profit": commission,
            "units": round(pnl, 4), "roi": round(pnl/len(selected), 6) if selected else None,
            "max_drawdown_units": round(drawdown, 4) if selected else None,
            "execution_assumption": "flat_1u_at_frozen_observed_odd_no_slippage"}


def walk_forward(rows: Iterable[Mapping[str, Any]], outcomes: Mapping[str, str], *, holdout_fraction: float = .30) -> dict[str, Any]:
    """Chronological holdout using only first frozen pre-game observation/version."""
    frozen = first_valid_by_match_and_version(rows)
    paired = []
    for row in frozen:
        pricing = row.get("pricing") if isinstance(row.get("pricing"), Mapping) else {}
        winner = outcomes.get(str(row.get("canonical_match_instance_id")))
        if winner not in ("a", "b") or pricing.get("economic_estimate_available") is False:
            continue
        model = pricing.get("sharp_estimate_a")
        market = pricing.get("market_probability_a")
        odd_a, odd_b = pricing.get("market_odd_a"), pricing.get("market_odd_b")
        try:
            model, market = float(model), float(market)
            odd_a, odd_b = float(odd_a), float(odd_b)
        except (TypeError, ValueError):
            continue
        paired.append({"time": row.get("analyzed_at_utc"), "segment": "challenger" if "challenger" in str(row.get("tier") or "").lower() else str(row.get("tour") or "").lower(),
                       "version": f"{row.get('model_version')}:{row.get('configuration_fingerprint')}",
                       "model": model, "market": market, "odd_a": odd_a,
                       "odd_b": odd_b,
                       "candidate_side": pricing.get("candidate_side") if pricing.get("candidate") is True else None,
                       "winner": winner, "y": 1.0 if winner == "a" else 0.0})
    paired.sort(key=lambda row: str(row["time"]))
    cut = max(1, int(len(paired) * (1.0 - holdout_fraction))) if paired else 0
    holdout = paired[cut:]
    def comparison(sample):
        model_rows = [{"p": r["model"], "y": r["y"], "odd": r["odd_a"]} for r in sample]
        market_rows = [{"p": r["market"], "y": r["y"], "odd": r["odd_a"]} for r in sample]
        m, k = _scores(model_rows), _scores(market_rows)
        neutral_rows = [{"p": .5, "y": r["y"], "odd": r["odd_a"]} for r in sample]
        return {"model": m, "market": k, "neutral": _scores(neutral_rows),
                "delta_brier": round(m["brier"]-k["brier"], 6) if m["n"] else None,
                "delta_log_loss": round(m["log_loss"]-k["log_loss"], 6) if m["n"] else None,
                "calibration": _calibration(model_rows),
                "shadow_selection": _selection_metrics(sample)}
    grouped = defaultdict(list)
    for row in holdout:
        grouped[(row["segment"], row["version"])].append(row)
    folds = []
    if paired:
        initial = max(1, int(len(paired) * .40))
        step = max(1, (len(paired) - initial) // 3)
        for start in range(initial, len(paired), step):
            block = paired[start:min(len(paired), start+step)]
            folds.append({"train_n": start, "test_n": len(block), "test": comparison(block)})
    return {"contract_version": "pricing-walk-forward-v1", "status": "SHADOW_ONLY",
            "train_size": cut, "holdout_size": len(holdout), "overall": comparison(holdout),
            "segments": {f"{k[0]}|{k[1]}": comparison(v) for k, v in sorted(grouped.items())},
            "expanding_window_folds": folds,
            "promotion_gate": {"passed": False, "reason": "manual_audit_required_and_no_automatic_promotion"}}
