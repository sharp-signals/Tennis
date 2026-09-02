"""Run the single bounded CHANGE-2026-09-02-023 coverage experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from src import fetch_data
from src.historical_enrichment import enrich_from_tennis_data, enrich_opponent_history
from src.historical_replay import replay_matches
from src.historical_warehouse import HistoricalWarehouse, canonical_json
from scripts.historical_replay import _assert_zero_llm


FEATURE_FIELDS = (
    "ranking_a", "ranking_b", "h2h", "recent_form_a", "recent_form_b",
    "surface_a", "surface_b",
)
MAX_EXPERIMENT_CALLS = 150
EXPECTED_BASELINE = {
    "ranking_a": 0, "ranking_b": 0, "h2h": 11,
    "recent_form_a": 85, "recent_form_b": 34, "surface_a": 0, "surface_b": 0,
}


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    ids = [str(item["match_id"]) for item in manifest.get("matches") or []]
    if len(ids) != len(set(ids)):
        raise RuntimeError("O manifesto contém IDs duplicados; o universo deve ter jogos únicos.")
    digest = hashlib.sha256(canonical_json(ids).encode("utf-8")).hexdigest()
    if digest != manifest.get("ordered_unique_ids_sha256"):
        raise RuntimeError("Hash do universo no manifesto não confere.")
    if len(ids) != 99:
        raise RuntimeError(f"O experimento exige exatamente os 99 jogos únicos do Pilot 100; recebeu {len(ids)}.")
    return manifest


def _coverage(metrics: dict[str, Any]) -> dict[str, Any]:
    unique = int(metrics["unique_matches_requested"])
    unavailable = metrics.get("unavailable_fields") or {}
    by_feature = {field: unique - int(unavailable.get(field, 0)) for field in FEATURE_FIELDS}
    available = sum(by_feature.values())
    total = unique * len(FEATURE_FIELDS)
    return {
        "available_feature_cells": available, "total_feature_cells": total,
        "coverage_ratio": round(available / total, 4) if total else 0.0,
        "by_feature": by_feature,
        "mean_features_per_snapshot": (metrics.get("available_features_per_snapshot") or {}).get("mean", 0.0),
        "snapshot_feature_histogram_0_to_7": (
            metrics.get("available_features_per_snapshot") or {}
        ).get("histogram_0_to_7", {}),
        "by_dimension": metrics.get("coverage_by_dimension") or {},
    }


def _comparison(before: dict[str, Any], after: dict[str, Any], unique: int) -> list[dict[str, Any]]:
    rows = []
    for field in FEATURE_FIELDS:
        first, last = before["by_feature"][field], after["by_feature"][field]
        rows.append({
            "feature": field, "before": first, "after": last, "delta": last - first,
            "before_pct": round(100 * first / unique, 1),
            "after_pct": round(100 * last / unique, 1),
            "delta_pp": round(100 * (last - first) / unique, 1),
        })
    return rows


def _provenance_summary(warehouse: HistoricalWarehouse, match_ids: list[str]) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in match_ids)
    original_fields = ("player_a_rank", "player_b_rank", "surface", "tournament", "tournament_level")
    with warehouse.connect() as connection:
        original = connection.execute(
            f"SELECT {','.join(original_fields)} FROM matches WHERE canonical_match_id IN ({placeholders})",
            match_ids,
        ).fetchall()
        enrichment_rows = connection.execute(
            f"""SELECT source, temporal_class, conflict, COUNT(*) AS count
                FROM match_enrichments WHERE match_id IN ({placeholders})
                GROUP BY source, temporal_class, conflict""",
            match_ids,
        ).fetchall()
    return {
        "original_rapidapi_non_null_attributes": sum(
            int(row[field] is not None) for row in original for field in original_fields
        ),
        "enriched_attributes": [dict(row) for row in enrichment_rows],
        "effective_precedence": "original_then_single_unambiguous_safe_enrichment",
    }


def _validate_seed(warehouse: HistoricalWarehouse, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for item in manifest["matches"]:
        match = warehouse.get_match(str(item["match_id"]))
        if match is None:
            raise RuntimeError(f"Jogo do manifesto ausente no seed: {item['match_id']}")
        for key in (
            "tour", "event_start_utc", "player_a_id", "player_a_name",
            "player_b_id", "player_b_name",
        ):
            if str(match.get(key)) != str(item.get(key)):
                raise RuntimeError(f"Seed diverge do manifesto em {item['match_id']} / {key}.")
        targets.append(match)
    return targets


def _write_reports(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "coverage-enrichment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    before, after = report["before"], report["after"]
    lines = [
        "# Historical Coverage Enrichment — CHANGE-2026-09-02-023", "",
        "> Coverage experiment only. No predictive performance or edge claim.", "",
        f"- Fixed universe: {report['sample']['unique_matches']} unique matches",
        f"- RapidAPI calls: {report['rapidapi']['calls_made']} / {report['rapidapi']['hard_limit']}",
        f"- RapidAPI calls by tour: {report['rapidapi']['calls_by_tour']}",
        f"- Cache hits: {report['rapidapi']['cache_hits']}",
        f"- Warehouse: {report['warehouse_size_bytes']} bytes", "",
        "| Feature | Before | After | Delta |", "|---|---:|---:|---:|",
    ]
    for field in FEATURE_FIELDS:
        first = before["feature_coverage"]["by_feature"][field]
        last = after["feature_coverage"]["by_feature"][field]
        lines.append(f"| {field} | {first} | {last} | {last-first:+d} |")
    lines.extend([
        "", f"Overall: {before['feature_coverage']['coverage_ratio']:.1%} → "
        f"{after['feature_coverage']['coverage_ratio']:.1%}.", "",
        f"H2H states after enrichment: {after['replay']['metrics'].get('h2h_status_counts', {})}.", "",
        "Odds imported from tennis-data.co.uk remain `UNAVAILABLE` for ex-ante pricing "
        "because bookmaker timestamp semantics are not proven.",
    ])
    (output_dir / "coverage-enrichment.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-warehouse", type=Path, required=True)
    parser.add_argument("--warehouse", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("data/historical_manifests/pilot100_v1.json"))
    parser.add_argument("--max-calls", type=int, default=150)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/historical-coverage-enrichment"))
    parser.add_argument("--tennis-data-cache", type=Path, default=Path("data/history_cache"))
    args = parser.parse_args()
    _assert_zero_llm()
    if not 0 <= args.max_calls <= MAX_EXPERIMENT_CALLS:
        parser.error(f"--max-calls must be between 0 and the authorized hard limit of {MAX_EXPERIMENT_CALLS}")
    if not args.seed_warehouse.exists():
        parser.error(f"seed warehouse not found: {args.seed_warehouse}")
    args.warehouse.parent.mkdir(parents=True, exist_ok=True)
    if args.seed_warehouse.resolve() != args.warehouse.resolve():
        shutil.copy2(args.seed_warehouse, args.warehouse)

    manifest = load_manifest(args.manifest)
    warehouse_size_before = args.seed_warehouse.stat().st_size
    warehouse = HistoricalWarehouse(args.warehouse)
    targets = _validate_seed(warehouse, manifest)
    match_ids = [str(item["match_id"]) for item in manifest["matches"]]
    fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN = min(fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN, args.max_calls)

    baseline = replay_matches(
        warehouse, match_ids, mode="coverage_enrichment_baseline",
        replay_version="historical-replay-v2-baseline",
    )
    observed_baseline = _coverage(baseline["metrics"])
    if observed_baseline["by_feature"] != EXPECTED_BASELINE:
        raise RuntimeError(
            f"Baseline do seed diverge do Pilot 100: {observed_baseline['by_feature']}"
        )
    opponent = enrich_opponent_history(
        warehouse, targets, max_calls=args.max_calls, required_prior_matches=10,
    )
    tennis_data = enrich_from_tennis_data(warehouse, cache_dir=args.tennis_data_cache)
    after = replay_matches(
        warehouse, match_ids, mode="coverage_enrichment",
        replay_version="historical-replay-v2-enriched",
    )
    acquisition = opponent["acquisition"]
    before_coverage = observed_baseline
    after_coverage = _coverage(after["metrics"])
    report = {
        "change_id": "CHANGE-2026-09-02-023",
        "scope": "coverage_only_no_predictive_claims",
        "sample": {
            "source_run_id": manifest["source_run_id"],
            "source_artifact": manifest["source_artifact"],
            "requested_positions_in_source": manifest["requested_positions"],
            "unique_matches": len(match_ids),
            "ordered_unique_ids_sha256": manifest["ordered_unique_ids_sha256"],
        },
        "rapidapi": {
            "calls_made": acquisition["calls_made"],
            "cache_hits": acquisition["cache_hits"],
            "calls_avoided_via_cache": acquisition["calls_avoided_via_cache"],
            "calls_by_tour": opponent["calls_by_tour"],
            "cache_hits_by_tour": opponent["cache_hits_by_tour"],
            "pages_by_tour": opponent["pages_by_tour"],
            "hard_limit": args.max_calls,
            "calls_per_unique_target": round(acquisition["calls_made"] / len(match_ids), 4),
            "linear_calls_estimate_for_1000_targets": round(acquisition["calls_made"] * 1000 / len(match_ids)),
        },
        "opponent_history": opponent,
        "tennis_data": tennis_data,
        "before": {"replay": baseline, "feature_coverage": before_coverage},
        "after": {"replay": after, "feature_coverage": after_coverage},
        "before_after_table": _comparison(before_coverage, after_coverage, len(match_ids)),
        "provenance": _provenance_summary(warehouse, match_ids),
        "warehouse_size_before_bytes": warehouse_size_before,
        "warehouse_size_after_bytes": warehouse.size_bytes(),
        "warehouse_size_bytes": warehouse.size_bytes(),
        "offline_replay_network_calls": 0,
        "anthropic_calls": 0,
        "limitations": [
            "tennis-data.co.uk odds have no proven observation timestamp and remain UNAVAILABLE",
            "ambiguous or non-unique pair/date joins are rejected",
            "missing values remain UNAVAILABLE and never become zero",
        ],
    }
    _write_reports(args.output_dir, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
