"""Read-only replay of historical Market Ledger identity evidence.

This is a diagnostic simulation, never a migration. It resolves observations
against a temporary empty registry and emits only aggregate counts. Existing
Ledger, snapshots, PAPER and the operational v2 registry are never written.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from src import market_ledger, match_identity_v2


def _match_from_observation(row: Mapping[str, Any]) -> dict[str, Any]:
    event = row.get("event") if isinstance(row.get("event"), Mapping) else {}
    player_a = event.get("player_a") if isinstance(event.get("player_a"), Mapping) else {}
    player_b = event.get("player_b") if isinstance(event.get("player_b"), Mapping) else {}
    return {
        "id": event.get("match_id"),
        "_tour": event.get("tour"),
        "tournamentId": event.get("tournament_id"),
        "date": event.get("scheduled_start_utc"),
        "player1Id": player_a.get("id"),
        "player2Id": player_b.get("id"),
        "player1": {"id": player_a.get("id"), "name": player_a.get("name")},
        "player2": {"id": player_b.get("id"), "name": player_b.get("name")},
    }


def simulate(root: Path) -> dict[str, Any]:
    rows = market_ledger.read_observations(root=root / "data/market_ledger")
    rows.sort(key=lambda row: (
        str((row.get("capture") or {}).get("captured_at_utc") or ""),
        str(row.get("observation_id") or ""),
    ))
    legacy_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    states: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(prefix="match-identity-v2-replay-") as temporary:
        temporary_root = Path(temporary)
        registry_path = temporary_root / "registry-v2.json"
        events_path = temporary_root / "events-v2.jsonl"
        for row in rows:
            event = row.get("event") if isinstance(row.get("event"), Mapping) else {}
            capture = row.get("capture") if isinstance(row.get("capture"), Mapping) else {}
            pair = tuple(sorted((
                str((event.get("player_a") or {}).get("id")),
                str((event.get("player_b") or {}).get("id")),
            )))
            legacy_pairs[str(event.get("event_key") or "UNAVAILABLE")].add(pair)
            mapping_status = capture.get("identity_mapping_status")
            result = match_identity_v2.resolve_observation(
                _match_from_observation(row),
                event_id=event.get("provider_event_id"),
                event_id_validated=match_identity_v2.event_id_is_bilaterally_validated(
                    mapping_status
                ),
                provider=str((row.get("source") or {}).get("provider") or "UNKNOWN"),
                observed_at_utc=str(capture.get("captured_at_utc") or "") or None,
                registry_path=registry_path,
                events_path=events_path,
                runtime_metadata={"runtime_sha": "READ_ONLY_SIMULATION"},
            )
            states[str(result.get("identity_status") or "UNAVAILABLE")] += 1
            reasons[str(result.get("identity_reason_code") or "UNAVAILABLE")] += 1
        registry = match_identity_v2.read_registry(registry_path)
        aliases = Counter(str(row.get("status") or "UNAVAILABLE") for row in registry["aliases"])
        event_count = len(events_path.read_text(encoding="utf-8").splitlines()) if events_path.exists() else 0
    reused = {key: pairs for key, pairs in legacy_pairs.items() if len(pairs) > 1}
    return {
        "mode": "READ_ONLY_SIMULATION_NO_BACKFILL",
        "change_id": match_identity_v2.CHANGE_ID,
        "identity_schema_version": match_identity_v2.SCHEMA_VERSION,
        "source": "existing local Market-Time Ledger",
        "observations_replayed": len(rows),
        "legacy_keys_observed": len(legacy_pairs),
        "legacy_keys_with_multiple_player_pairs": len(reused),
        "player_pairs_represented_by_reused_legacy_keys": sum(len(pairs) for pairs in reused.values()),
        "resolver_states": dict(sorted(states.items())),
        "reason_codes": dict(sorted(reasons.items())),
        "temporary_canonical_instances": len(registry["instances"]),
        "temporary_aliases_by_status": dict(sorted(aliases.items())),
        "temporary_audit_events": event_count,
        "operational_registry_written": False,
        "historical_artifacts_written": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(simulate(args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
