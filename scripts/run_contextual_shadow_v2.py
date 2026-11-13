"""Collect prospective contextual v2 observations without running the bot.

This entry point deliberately avoids market prices, reports, notifications,
PAPER, GREEN, dashboards and settlement.  It is the only supported way to
start the prospective v2 cohort while the operational bot remains paused.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_contextual_shadow_v2 import audit_ledger  # noqa: E402
from src import fetch_data, match_identity_v2  # noqa: E402
from src.contextual_family_replay import (  # noqa: E402
    apply_h2h_override,
    build_contextual_target_row,
)
from src.contextual_shadow_activation_v2 import activation_state  # noqa: E402
from src.contextual_shadow_handicap_v2 import (  # noqa: E402
    append_frozen_handicap_evidence,
    build_frozen_handicap_evidence,
    infer_match_format,
)
from src.contextual_shadow_h2h_evidence_v1 import (  # noqa: E402
    append_frozen_h2h_evidence,
    build_frozen_h2h_evidence,
)
from src.contextual_shadow_moneyline_v1 import (  # noqa: E402
    append_frozen_moneyline_evidence,
    build_frozen_moneyline_evidence,
)
from src.contextual_shadow_runtime_v2 import (  # noqa: E402
    load_contract,
    predict_contextual_shadow_v2,
)
from src.contextual_shadow_store_v2 import (  # noqa: E402
    DEFAULT_PATH as LEDGER_PATH,
    append_observations,
    build_observation,
    existing_observation_ids,
)
from src.main import (  # noqa: E402
    _deduplicate_matches,
    _filter_and_enrich_with_tournament_info,
    _filter_matches_in_window,
    _filter_prelive_matches,
    _parse_utc,
)
from src.round_stage import classify_round_stage  # noqa: E402


SUMMARY_PATH = Path("data/validation/contextual-shadow-v2-latest.json")
MODEL_PATH = Path("data/models/contextual-family-shadow-v2.json")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _player(match: Mapping[str, Any], side: int) -> tuple[str, Any]:
    player = match.get(f"player{side}") or {}
    name = str(player.get("name") or "").strip()
    player_id = match.get(f"player{side}Id") or player.get("id")
    return name, player_id


def _ranking(
    history, official: Any, player_name: str, player_id: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    entry, source = fetch_data.resolve_official_ranking(
        official, player_name, player_id,
    )
    if entry:
        return {
            "rank": entry.get("rank"),
            "points": entry.get("points"),
        }, source
    historical = fetch_data.get_player_ranking(history, player_name)
    return historical, "local_history" if historical is not None else None


def _model_player_id(
    model_name: str, *, original_a: str, original_b: str,
    resolved_a: str, resolved_b: str, id_a: Any, id_b: Any,
) -> Any:
    normalized = fetch_data._normalize_name(model_name)
    if normalized in {
        fetch_data._normalize_name(original_a),
        fetch_data._normalize_name(resolved_a),
    }:
        return id_a
    if normalized in {
        fetch_data._normalize_name(original_b),
        fetch_data._normalize_name(resolved_b),
    }:
        return id_b
    return None


_NON_COMPETITIVE_H2H_MARKERS = (
    "exhibition", "world tennis league", "laver cup",
    "ultimate tennis showdown",
)


def _provider_h2h_override(
    *, tour: str, player_a_id: Any, player_b_id: Any,
    current_surface: Any, cutoff: datetime,
) -> dict[str, Any] | None:
    """Build a transparent competitive H2H sample from the factual endpoint."""
    if player_a_id is None or player_b_id is None:
        return None
    try:
        provider_a_id, provider_b_id = int(player_a_id), int(player_b_id)
    except (TypeError, ValueError):
        return None
    matches, coverage = fetch_data.fetch_h2h_matches_with_coverage(
        tour, provider_a_id, provider_b_id,
    )
    if not matches:
        return None
    current_family = fetch_data._normalize_surface_family(current_surface)
    eligible = []
    excluded = []
    surface_rows = []
    for source in matches:
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        played_at = row.get("date") or row.get("startTimestamp")
        played = None
        if played_at:
            try:
                if isinstance(played_at, (int, float)):
                    played = datetime.fromtimestamp(float(played_at), timezone.utc)
                else:
                    played = _parse_utc(str(played_at))
                if played >= cutoff:
                    continue
            except (TypeError, ValueError):
                pass
        tournament = row.get("tournament") or {}
        tournament_name = str(
            row.get("tournament_name") or row.get("tournamentName")
            or (tournament.get("name") if isinstance(tournament, Mapping) else "")
            or ""
        ).strip()
        surface = row.get("surface") or row.get("court")
        tournament_id = row.get("tournamentId")
        if tournament_id is not None and (not tournament_name or not surface):
            try:
                info = fetch_data.get_tournament_info(tournament_id, tour) or {}
            except Exception:
                info = {}
            tournament_name = tournament_name or str(info.get("name") or "")
            surface = surface or info.get("surface")
        normalized_name = tournament_name.casefold()
        if any(marker.casefold() in normalized_name for marker in _NON_COMPETITIVE_H2H_MARKERS):
            excluded.append({"tournament": tournament_name, "reason": "NON_COMPETITIVE"})
            continue
        winner = row.get("match_winner") or row.get("winnerId") or row.get("winner")
        if str(winner) not in {str(player_a_id), str(player_b_id)}:
            continue
        row["_display_date"] = played.date().isoformat() if played else None
        row["_display_tournament"] = tournament_name or "Torneio não identificado"
        row["_display_surface"] = surface
        row["_display_winner_side"] = (
            "a" if str(winner) == str(player_a_id) else "b"
        )
        eligible.append(row)
        if current_family and fetch_data._normalize_surface_family(surface) == current_family:
            surface_rows.append(row)
    if not eligible:
        return None
    return {
        "source": str(coverage.get("source") or f"rapidapi_{tour}_h2h_matches"),
        "raw_matches": len(matches),
        "eligible_matches": len(eligible),
        "eligible_a_wins": sum(
            str(row.get("match_winner") or row.get("winnerId") or row.get("winner"))
            == str(player_a_id) for row in eligible
        ),
        "eligible_surface_matches": len(surface_rows),
        "eligible_surface_a_wins": sum(
            str(row.get("match_winner") or row.get("winnerId") or row.get("winner"))
            == str(player_a_id) for row in surface_rows
        ),
        "excluded_non_competitive": len(excluded),
        "excluded_rows": excluded,
        "matches": sorted(
            [
                {
                    "event_date": row.get("_display_date"),
                    "tournament": row.get("_display_tournament"),
                    "surface": row.get("_display_surface"),
                    "winner_side": row.get("_display_winner_side"),
                    "score": (
                        row.get("result") or row.get("score")
                        or row.get("finalScore")
                    ),
                    "round": row.get("roundName") or row.get("round"),
                }
                for row in eligible
            ],
            key=lambda item: str(item.get("event_date") or ""),
            reverse=True,
        ),
    }


def build_match_observation(
    match: Mapping[str, Any], *, official_rankings: Mapping[str, Any],
    contract: Mapping[str, Any], analyzed_at_utc: str,
    predictor=predict_contextual_shadow_v2,
    observation_builder=build_observation,
    payload_key: str = "contextual_shadow_v2",
    model_version: str = "contextual-family-shadow-v2",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    tour = str(match.get("_tour") or "").strip().casefold()
    if tour not in {"atp", "wta"}:
        return None, {"status": "SKIPPED", "reason_code": "UNSUPPORTED_TOUR"}
    if str(match.get("tier") or "").strip() == "Challenger 125":
        return None, {
            "status": "SKIPPED",
            "reason_code": "CHALLENGER_MODEL_NOT_CALIBRATED",
        }
    original_a, id_a = _player(match, 1)
    original_b, id_b = _player(match, 2)
    if not original_a or not original_b:
        return None, {
            "status": "SKIPPED", "reason_code": "PLAYER_IDENTITY_MISSING",
        }
    if tour == "atp":
        context_history = fetch_data.get_history("atp", tier="Challenger 125")
        history = fetch_data.filter_history_scope(context_history, "main")
    else:
        context_history = fetch_data.get_history(tour, tier=match.get("tier"))
        history = context_history
    if history.empty or context_history.empty:
        return None, {"status": "SKIPPED", "reason_code": "HISTORY_EMPTY"}
    historical_odds_history = fetch_data.get_historical_odds_history(tour)
    resolved_a = fetch_data.resolve_player_name(context_history, original_a) or original_a
    resolved_b = fetch_data.resolve_player_name(context_history, original_b) or original_b
    rank_a, rank_source_a = _ranking(
        history, official_rankings.get(tour), original_a, id_a,
    )
    rank_b, rank_source_b = _ranking(
        history, official_rankings.get(tour), original_b, id_b,
    )
    start = _parse_utc(str(match["date"]))
    row = build_contextual_target_row(
        context_history,
        universe=tour,
        player_a=resolved_a,
        player_b=resolved_b,
        cutoff=start.date(),
        surface=match.get("surface"),
        rank_a=(rank_a or {}).get("rank"),
        rank_b=(rank_b or {}).get("rank"),
        points_a=(rank_a or {}).get("points"),
        points_b=(rank_b or {}).get("points"),
        venue=(
            match.get("indoor") if match.get("indoor") is not None
            else match.get("venue_context")
        ),
        pace_bucket=(
            match.get("court_pace_bucket") or match.get("pace_bucket")
        ),
        target_tier=match.get("tier"),
    )
    model_a_id = _model_player_id(
        str(row["player_a"]), original_a=original_a, original_b=original_b,
        resolved_a=resolved_a, resolved_b=resolved_b, id_a=id_a, id_b=id_b,
    )
    model_b_id = _model_player_id(
        str(row["player_b"]), original_a=original_a, original_b=original_b,
        resolved_a=resolved_a, resolved_b=resolved_b, id_a=id_a, id_b=id_b,
    )
    row = apply_h2h_override(row, _provider_h2h_override(
        tour=tour, player_a_id=model_a_id, player_b_id=model_b_id,
        current_surface=match.get("surface"), cutoff=start,
    ))
    shadow = predictor(row, contract, universe=tour)
    identity = match_identity_v2.resolve_observation(
        match,
        provider="RapidAPI",
        observed_at_utc=analyzed_at_utc,
        runtime_metadata={
            "runtime_sha": os.environ.get("GITHUB_SHA"),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        },
    )
    canonical = identity.get("canonical_match_instance_id")
    if not canonical:
        return None, {
            "status": "SKIPPED",
            "reason_code": identity.get("identity_reason_code")
            or identity.get("reason_code") or "CANONICAL_IDENTITY_UNAVAILABLE",
        }
    model_a = str(row["player_a"])
    model_b = str(row["player_b"])
    payload = {
        "canonical_match_instance_id": canonical,
        "event_key": canonical,
        "tour": tour,
        "tier": match.get("tier"),
        "commence_time_utc": start.isoformat(),
        "analyzed_at_utc": analyzed_at_utc,
        "player_a_id": model_a_id,
        "player_b_id": model_b_id,
        "player_a": model_a,
        "player_b": model_b,
        "competition": {
            "tournament_id": match.get("tournamentId"),
            "tournament_name": match.get("tournament_name"),
            "round_id": match.get("roundId") or match.get("round_id"),
            "round_stage": classify_round_stage(
                round_id=match.get("roundId") or match.get("round_id"),
                round_label=match.get("round") or match.get("round_name"),
            ),
            "surface": match.get("surface"),
            "country": match.get("country"),
            "venue": (
                match.get("indoor") if match.get("indoor") is not None
                else match.get("venue_context")
            ),
            "pace_bucket": (
                match.get("court_pace_bucket") or match.get("pace_bucket")
            ),
        },
        payload_key: shadow,
    }
    observation = observation_builder(payload)
    if observation is None:
        return None, {
            "status": "FAILED",
            "reason_code": "OBSERVATION_CONTRACT_REJECTED",
        }
    handicap_evidence = build_frozen_handicap_evidence(
        history,
        observation_id=str(observation["observation_id"]),
        configuration_fingerprint=str(shadow["configuration_fingerprint"]),
        player_a=model_a,
        player_b=model_b,
        cutoff=start.date(),
        match_format=infer_match_format(match),
        captured_at_utc=analyzed_at_utc,
        model_version=model_version,
    )
    moneyline_evidence = build_frozen_moneyline_evidence(
        historical_odds_history,
        observation_id=str(observation["observation_id"]),
        configuration_fingerprint=str(shadow["configuration_fingerprint"]),
        player_a=model_a,
        player_b=model_b,
        cutoff=start.date(),
        captured_at_utc=analyzed_at_utc,
        model_version=model_version,
    )
    h2h_evidence = build_frozen_h2h_evidence(
        observation,
        captured_at_utc=analyzed_at_utc,
        model_version=model_version,
    )
    return observation, {
        "status": shadow["status"],
        "reason_code": ",".join(shadow["reason_codes"]) or "READY",
        "tour": tour,
        "quality_group": shadow["quality_group"],
        "rank_sources": {"a": rank_source_a, "b": rank_source_b},
        "_handicap_evidence": handicap_evidence,
        "_moneyline_evidence": moneyline_evidence,
        "_h2h_evidence": h2h_evidence,
    }


def _run_shadow_only(
    *, max_matches: int = 0, workers: int = 4,
    activation_loader=activation_state,
    disabled_code: str = "CONTEXTUAL_SHADOW_V2_DISABLED",
    activation_env: str = "CONTEXTUAL_SHADOW_V2_MODE",
    model_path: Path = MODEL_PATH,
    ledger_path: Path = LEDGER_PATH,
    summary_path: Path = SUMMARY_PATH,
    contract_loader=load_contract,
    predictor=predict_contextual_shadow_v2,
    observation_builder=build_observation,
    observation_ids_loader=existing_observation_ids,
    observation_appender=append_observations,
    payload_key: str = "contextual_shadow_v2",
    model_version: str = "contextual-family-shadow-v2",
    handicap_path: Path | None = None,
    moneyline_path: Path | None = None,
    h2h_path: Path | None = None,
    usage_status: str = "shadow_v2_success",
) -> dict[str, Any]:
    activation = activation_loader()
    if activation["active"] is not True:
        raise RuntimeError(
            f"{disabled_code}: set {activation_env}=observe explicitly"
        )
    reset_calls = getattr(fetch_data, "reset_rapidapi_call_count", None)
    if callable(reset_calls):
        reset_calls()
    raw = fetch_data.fetch_resilient_discovery_fixtures()
    if not raw and fetch_data.discovery_unavailable():
        raise RuntimeError("DISCOVERY_UNAVAILABLE")
    eligible = _filter_and_enrich_with_tournament_info(
        _filter_prelive_matches(
            _filter_matches_in_window(_deduplicate_matches(raw))
        )
    )
    eligible = [
        match for match in eligible
        if str(match.get("_tour") or "").casefold() in {"atp", "wta"}
        and str(match.get("tier") or "").strip() != "Challenger 125"
    ]
    if max_matches > 0:
        eligible = eligible[:max_matches]
    official_rankings = {
        tour: fetch_data.fetch_official_ranking(tour) for tour in ("atp", "wta")
    }
    contract = contract_loader(model_path)
    analyzed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def process(match):
        try:
            return build_match_observation(
                match,
                official_rankings=official_rankings,
                contract=contract,
                analyzed_at_utc=analyzed_at,
                predictor=predictor,
                observation_builder=observation_builder,
                payload_key=payload_key,
                model_version=model_version,
            )
        except Exception as exc:
            return None, {
                "status": "FAILED",
                "reason_code": type(exc).__name__,
                "detail": str(exc)[:160],
            }

    observations = []
    handicap_evidence = []
    moneyline_evidence = []
    h2h_evidence = []
    diagnostics = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        for observation, diagnostic in executor.map(process, eligible):
            evidence = diagnostic.pop("_handicap_evidence", None)
            moneyline = diagnostic.pop("_moneyline_evidence", None)
            h2h = diagnostic.pop("_h2h_evidence", None)
            diagnostics.append(diagnostic)
            if observation is not None:
                observations.append(observation)
                if evidence is not None:
                    handicap_evidence.append(evidence)
                if moneyline is not None:
                    moneyline_evidence.append(moneyline)
                if h2h is not None:
                    h2h_evidence.append(h2h)
    existing_ids = observation_ids_loader(ledger_path)
    new_ids = {
        str(row.get("observation_id")) for row in observations
        if str(row.get("observation_id") or "") not in existing_ids
    }
    added = observation_appender(observations, ledger_path)
    handicap_added = append_frozen_handicap_evidence(
        (
            row for row in handicap_evidence
            if str(row.get("observation_id") or "") in new_ids
        ),
        **({"path": handicap_path} if handicap_path is not None else {}),
    )
    moneyline_added = append_frozen_moneyline_evidence(
        (
            row for row in moneyline_evidence
            if str(row.get("observation_id") or "") in new_ids
        ),
        **({"path": moneyline_path} if moneyline_path is not None else {}),
    )
    h2h_added = append_frozen_h2h_evidence(
        h2h_evidence,
        **({"path": h2h_path} if h2h_path is not None else {}),
    )
    audit = audit_ledger(ledger_path, model_path)
    reason_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for item in diagnostics:
        reason = str(item.get("reason_code") or "UNKNOWN")
        status = str(item.get("status") or "UNKNOWN")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
    def count_by_tour(rows, *, observation_rows: bool = False) -> dict[str, int]:
        counts = {"atp": 0, "wta": 0}
        for row in rows:
            value = row.get("tour") if observation_rows else row.get("_tour")
            tour = str(value or "").casefold()
            if tour in counts:
                counts[tour] += 1
        return counts

    discovery_diagnostics = fetch_data.get_discovery_diagnostics()
    summary = {
        "schema_version": 1,
        "mode": "PROSPECTIVE_SHADOW_ONLY",
        "model_version": (
            contract.get("global_release_id") or contract["model_version"]
        ),
        "component_versions": dict(contract.get("components") or {}),
        "configuration_fingerprint": contract["configuration_fingerprint"],
        "analyzed_at_utc": analyzed_at,
        "fixtures_discovered": len(raw),
        "fixtures_discovered_by_tour": count_by_tour(raw),
        "eligible_main_tour": len(eligible),
        "eligible_main_tour_by_tour": count_by_tour(eligible),
        "observations_built": len(observations),
        "observation_ids_built": [
            str(row.get("observation_id")) for row in observations
            if row.get("observation_id")
        ],
        "observations_built_by_tour": count_by_tour(
            observations, observation_rows=True,
        ),
        "observations_added": added,
        "handicap_evidence_added": handicap_added,
        "moneyline_evidence_added": moneyline_added,
        "h2h_evidence_added": h2h_added,
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        "ledger_audit": audit,
        "tournament_filter_by_tour": discovery_diagnostics.get(
            "tournament_filter_by_tour", {}
        ),
        "isolation": {
            "market_used": False,
            "reports_published": False,
            "notifications_sent": False,
            "paper_created": False,
            "green_created": False,
        },
    }
    _write_json_atomic(summary_path, summary)
    fetch_data.flush_tournament_cache()
    fetch_data.flush_fixtures_cache()
    fetch_data.persist_rapidapi_usage(
        status=usage_status, matches=len(observations),
    )
    if audit["status"] == "CONTRACT_VIOLATION":
        raise RuntimeError("CONTEXTUAL_SHADOW_V2_CONTRACT_VIOLATION")
    return summary


def run_shadow_only(*, max_matches: int = 0, workers: int = 4) -> dict[str, Any]:
    return _run_shadow_only(
        max_matches=max_matches,
        workers=workers,
        activation_loader=activation_state,
        model_path=MODEL_PATH,
        ledger_path=LEDGER_PATH,
        summary_path=SUMMARY_PATH,
        contract_loader=load_contract,
        predictor=predict_contextual_shadow_v2,
        observation_builder=build_observation,
        observation_ids_loader=existing_observation_ids,
        observation_appender=append_observations,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-matches", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    summary = run_shadow_only(
        max_matches=max(0, args.max_matches), workers=max(1, args.workers),
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
