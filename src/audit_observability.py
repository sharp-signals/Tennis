"""Additive, offline audit projections. Never a decision or promotion gate."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import market_ledger, market_memory_report

CONTRACT = "PAIRED_PRICING_MARKET_V1"
CHANGE_ID = "CHANGE-2026-09-08-030"


def mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def timestamp(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def probabilities(pricing: Mapping, prefix: str) -> dict | None:
    """Full-precision frozen values preferred; no recomputation of pricing."""
    values = {side: number(pricing.get(f"{prefix}_{side}")) for side in ("a", "b")}
    if any(v is None or not 0 < v < 1 for v in values.values()):
        return None
    return values if abs(sum(values.values()) - 1) <= 1e-9 else None


def _scores(rows: list[dict]) -> dict:
    market = market_memory_report.evaluate_probabilities(rows, "market")
    model = market_memory_report.evaluate_probabilities(rows, "model")
    return {"sample_size": len(rows), "market": market, "fenzobot": model,
            "delta": {key: round(model[key] - market[key], 6) if rows else None
                      for key in ("brier_score", "log_loss")}}


def paired_comparison(snapshots: Any, observations: Any) -> dict:
    """Identical settled pairs, frozen pricing market, strict temporal linkage.

    Eligibility never reads outcome. Historical membership is descriptive,
    not prospective OOS. Duplicate keys/events are rejected as a group.
    """
    result = {"contract_version": CONTRACT, "change_id": CHANGE_ID,
              "mode": "RETROSPECTIVE_DESCRIPTIVE", "claims": "EXPERIMENTAL_NOT_VALIDATED",
              "probability_basis": "FROZEN_PRICING_FULL_PRECISION",
              "status": "UNAVAILABLE", "eligible_forecasts": None,
              "pending_or_unresolved": None, "sample_size": None,
              "by_pricing_version": {}, "by_code_revision": {}, "exclusions": {}}
    if not isinstance(snapshots, list) or not isinstance(observations, list):
        return result
    rows = [s for s in snapshots if isinstance(s, Mapping)]
    exclusions = Counter({"MALFORMED_SNAPSHOT": len(snapshots) - len(rows)})
    keys = Counter(s.get("key") for s in rows if isinstance(s.get("key"), str))
    events = Counter(s.get("event_key") or s.get("key") for s in rows
                     if isinstance(s.get("event_key") or s.get("key"), str))
    by_id = {}
    conflicting_ids = set()
    for obs in observations:
        oid = mapping(obs).get("observation_id")
        if not isinstance(oid, str):
            continue
        if oid in by_id and by_id[oid] != obs:
            conflicting_ids.add(oid)
        by_id[oid] = obs
    eligible, scored = [], []
    versions, revisions = defaultdict(list), defaultdict(list)
    for s in rows:
        key, event = s.get("key"), s.get("event_key") or s.get("key")
        p = mapping(s.get("pricing"))
        prov = mapping(s.get("odds_provenance"))
        oid = s.get("entry_market_observation_id")
        obs = mapping(by_id.get(oid)) if isinstance(oid, str) else {}
        market, model = probabilities(p, "market_probability"), probabilities(p, "sharp_estimate")
        analyzed, start = timestamp(s.get("analyzed_at_utc")), timestamp(s.get("commence_time_utc"))
        capture = timestamp(prov.get("captured_at_utc"))
        oe, oc, source = mapping(obs.get("event")), mapping(obs.get("capture")), mapping(obs.get("source"))
        reason = None
        if not isinstance(key, str) or not key or not isinstance(event, str):
            reason = "IDENTITY_UNAVAILABLE"
        elif keys[key] != 1 or events[event] != 1:
            reason = "DUPLICATE_IDENTITY"
        elif s.get("universe") not in (None, "SHADOW") or s.get("mode") == "BACKTEST_RECONSTRUCTED":
            reason = "WRONG_UNIVERSE"
        elif p.get("available") is not True or not market or not model:
            reason = "FROZEN_PROBABILITIES_UNAVAILABLE"
        elif not all((analyzed, start, capture)) or not capture <= analyzed < start:
            reason = "TEMPORAL_PROVENANCE_INVALID"
        elif not obs or oid in conflicting_ids or mapping(obs.get("eligibility")).get("market_memory") is not True:
            reason = "ENTRY_LINK_UNAVAILABLE"
        elif (oe.get("event_key") != event or timestamp(oe.get("scheduled_start_utc")) != start
              or timestamp(oc.get("captured_at_utc")) != capture
              or oc.get("identity_mapping_status") != "VERIFIED"):
            reason = "ENTRY_IDENTITY_OR_TIME_MISMATCH"
        elif (not prov.get("bookmaker") or prov.get("bookmaker") != source.get("bookmaker")
              or not prov.get("endpoint") or prov.get("endpoint") != source.get("endpoint")
              or mapping(obs.get("market")).get("type") != "MONEYLINE"):
            reason = "ENTRY_MARKET_MISMATCH"
        else:
            for side in ("a", "b"):
                selection = next((x for x in obs.get("selections", [])
                                  if isinstance(x, Mapping) and x.get("side") == side), {})
                odd, expected = number(selection.get("raw_decimal_odd")), number(p.get(f"market_odd_{side}"))
                player, linked = mapping(s.get(f"player_{side}")), mapping(oe.get(f"player_{side}"))
                if (not player.get("id") or player.get("id") != linked.get("id")
                        or odd is None or expected is None or odd <= 1 or odd != expected):
                    reason = "ENTRY_SIDE_OR_ODDS_MISMATCH"
                    break
            if not reason:
                weights = {side: 1 / float(p[f"market_odd_{side}"]) for side in ("a", "b")}
                if any(abs(market[side] - weights[side] / sum(weights.values())) > 1e-9 for side in weights):
                    reason = "PRICING_MARKET_PROBABILITY_MISMATCH"
        if reason:
            exclusions[reason] += 1
            continue
        # Eligibility and this fingerprint are independent of the outcome.
        version = [p.get("model_version") or "UNAVAILABLE", p.get("configuration_fingerprint") or "UNAVAILABLE"]
        membership = mapping(mapping(mapping(s.get("validation")).get("cohorts")).get("GREEN_STRONG_V1"))
        revision = mapping(membership.get("source")).get("code_revision") or "UNAVAILABLE"
        eligible.append({"key": key, "market": market, "model": model, "entry": oid,
                         "analyzed_at_utc": s.get("analyzed_at_utc"), "pricing_version": version})
        outcome = mapping(s.get("outcome")).get("winner_side")
        if outcome in ("a", "b"):
            row = {"key": key, "market": market, "model": model, "outcome_side": outcome}
            scored.append(row)
            versions[json.dumps(version)].append(row)
            revisions[str(revision)].append(row)
    result.update(_scores(scored))
    result.update({"status": "AVAILABLE", "total_snapshots": len(snapshots),
                   "eligible_forecasts": len(eligible), "pending_or_unresolved": len(eligible) - len(scored),
                   "eligibility_hash": digest(sorted(eligible, key=lambda x: x["key"])),
                   "scored_snapshot_keys_hash": digest(sorted(r["key"] for r in scored)),
                   "exclusions": {k: v for k, v in sorted(exclusions.items()) if v},
                   "by_pricing_version": {k: _scores(v) for k, v in sorted(versions.items())},
                   "by_code_revision": {k: _scores(v) for k, v in sorted(revisions.items())}})
    return result


def green_diagnostics(snapshots: Any) -> dict:
    if not isinstance(snapshots, list):
        return {"status": "UNAVAILABLE"}
    counts, reasons = Counter(), Counter()
    for s in snapshots:
        s = mapping(s)
        membership = mapping(mapping(mapping(s.get("validation")).get("cohorts")).get("GREEN_STRONG_V1"))
        if not membership or membership.get("prospective") is not True:
            counts["legacy_or_not_prospective"] += 1
            continue
        counts["prospectively_classified"] += 1
        source = mapping(membership.get("source"))
        counts["decision_positive"] += source.get("decision_state") == "EDGE_POSITIVE"
        counts["direction_strong"] += source.get("divergence_type") == "direcao" and source.get("divergence_level") == 3
        counts["eligible"] += membership.get("eligible") is True
        counts["eligible_settled"] += membership.get("eligible") is True and mapping(s.get("outcome")).get("winner_side") in ("a", "b")
        for reason in set(membership.get("reason_codes") or []):
            # Known enum-like reason codes only, not arbitrary source text.
            if isinstance(reason, str) and reason.isascii() and reason.replace("_", "").isalnum() and reason.isupper():
                reasons[reason] += 1
    names = ("legacy_or_not_prospective", "prospectively_classified", "decision_positive",
             "direction_strong", "eligible", "eligible_settled")
    return {"status": "AVAILABLE", "total_snapshots": len(snapshots),
            **{name: counts[name] for name in names}, "exclusion_reason_counts": dict(sorted(reasons.items())),
            "note": "Independent stored gates, not an inferred sequential funnel; reasons may overlap."}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def build(root: Path, snapshots_doc: Any, dashboard: Mapping) -> dict:
    """Read primary sources; additions never modify existing metric fields."""
    snapshots = mapping(snapshots_doc).get("snapshots")
    try:
        observations = market_ledger.read_observations(root=root / "data/market_ledger")
        if not (root / "data/market_ledger").exists():
            observations = None
        ledger_status = "AVAILABLE" if observations is not None else "UNAVAILABLE"
    except Exception:
        observations, ledger_status = None, "INVALID"
    monitor = mapping(read_json(root / "data/odds_monitor/status.json"))
    quality = mapping(monitor.get("recent_odds_quote_quality"))
    report_counts = Counter(r.get("linkage", "UNAVAILABLE")
                            for d in dashboard.get("days", []) for r in d.get("reports", [])
                            if r.get("color") == "UNAVAILABLE")
    runs = read_json(root / "data/run_metrics_log.json")
    latest = mapping(runs[-1]) if isinstance(runs, list) and runs else {}
    refresh = mapping(read_json(root / "data/dashboard/refresh-status-v1.json"))
    return {"last_refresh_attempt": {k: refresh.get(k) for k in ("attempted_at_utc", "market_memory", "green_strong")},
            "contract_version": "audit-observability-v1", "change_id": CHANGE_ID,
            "paired_comparison": paired_comparison(snapshots, observations),
            "green_diagnostics": green_diagnostics(snapshots),
            "unknown_colors_by_linkage": dict(sorted(report_counts.items())),
            "ledger_status": ledger_status,
            "source_quality": {"last_monitor_capture_utc": monitor.get("last_run_at_utc"),
                               "fresh": number(quality.get("fresh")), "stale": number(quality.get("stale")),
                               "unknown": number(quality.get("unknown")),
                               "basis": "MONITOR_DIAGNOSTIC_NOT_PRICING_GATE",
                               "first_ledger_capture_utc": next((mapping(o.get("capture")).get("captured_at_utc") for o in observations or []), None)},
            "llm": {key: latest.get(key) for key in ("llm_provider_invocations", "llm_external_requests", "llm_mode")},
            "units": {"total_reports": "HTML_FILES_INCLUDING_RERUNS", "total_snapshots": "STORED_SNAPSHOTS",
                      "selected_candidates": "UNIQUE_SNAPSHOT_KEYS", "paper_entries": "LEGS_NOT_INDEPENDENT_MATCHES"}}
