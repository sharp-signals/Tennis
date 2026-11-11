"""Frozen post-prediction market benchmark for contextual SHADOW v2."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from .pricing import de_vig_market_probabilities


MARKET_PATH = Path("data/contextual_shadow_market-v2.jsonl")
MODEL_VERSION = "contextual-family-shadow-v2"
MATCH_WINDOW_SECONDS = 2 * 60 * 60


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fixture_player(fixture: Mapping[str, Any], side: int) -> tuple[Any, str]:
    nested = fixture.get(f"player{side}") or {}
    return (
        fixture.get(f"player{side}Id") or nested.get("id"),
        str(nested.get("name") or "").strip(),
    )


def match_fixture(
    observation: Mapping[str, Any], fixtures: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Resolve a fixture with exact bilateral IDs, tour and nearby start."""
    players = observation.get("players") or {}
    a_id = (players.get("a") or {}).get("id")
    b_id = (players.get("b") or {}).get("id")
    start = _parse_time(observation.get("commence_time_utc"))
    tour = str(observation.get("tour") or "").casefold()
    if a_id in (None, "") or b_id in (None, "") or start is None:
        return None
    wanted = frozenset((str(a_id), str(b_id)))
    candidates: list[tuple[float, Mapping[str, Any]]] = []
    for fixture in fixtures:
        if str(fixture.get("_tour") or "").casefold() != tour:
            continue
        p1_id, _ = _fixture_player(fixture, 1)
        p2_id, _ = _fixture_player(fixture, 2)
        if p1_id in (None, "") or p2_id in (None, ""):
            continue
        if frozenset((str(p1_id), str(p2_id))) != wanted:
            continue
        fixture_start = _parse_time(fixture.get("date"))
        if fixture_start is None:
            continue
        delta = abs((fixture_start - start).total_seconds())
        if delta <= MATCH_WINDOW_SECONDS:
            candidates.append((delta, fixture))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None
    if len(candidates) > 1 and math.isclose(
        candidates[0][0], candidates[1][0], abs_tol=1.0,
    ):
        return None
    return dict(candidates[0][1])


def _odd_for_fixture_side(
    odds: Mapping[str, Any], name: str,
) -> float | None:
    for key, value in odds.items():
        if str(key).strip().casefold() != name.casefold():
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed > 1.0 else None
    return None


def build_market_observation(
    observation: Mapping[str, Any],
    fixture: Mapping[str, Any],
    odds: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    model_version: str = MODEL_VERSION,
) -> dict[str, Any] | None:
    """Build a benchmark only after prediction freeze and before match start."""
    analyzed = _parse_time(observation.get("analyzed_at_utc"))
    captured = _parse_time(provenance.get("captured_at_utc"))
    commence = _parse_time(observation.get("commence_time_utc"))
    if not analyzed or not captured or not commence:
        return None
    if captured < analyzed or captured >= commence:
        return None
    if provenance.get("operational_pricing_eligible") is not True:
        return None
    bookmaker = str(provenance.get("bookmaker") or "").strip()
    if not bookmaker:
        return None
    linked = match_fixture(observation, [fixture])
    if linked is None:
        return None
    p1_id, p1_name = _fixture_player(fixture, 1)
    p2_id, p2_name = _fixture_player(fixture, 2)
    odd_1 = _odd_for_fixture_side(odds, p1_name)
    odd_2 = _odd_for_fixture_side(odds, p2_name)
    if odd_1 is None or odd_2 is None:
        return None
    players = observation.get("players") or {}
    a_id = (players.get("a") or {}).get("id")
    if str(a_id) == str(p1_id):
        odd_a, odd_b = odd_1, odd_2
    elif str(a_id) == str(p2_id):
        odd_a, odd_b = odd_2, odd_1
    else:
        return None
    probability_a, probability_b, overround = de_vig_market_probabilities(
        odd_a, odd_b,
    )
    observation_id = str(observation.get("observation_id") or "")
    if not observation_id:
        return None
    # A previsão continua imutável, mas o preço pode mudar entre execuções.
    # A identidade da cotação usa o conteúdo observado (não apenas a hora da
    # nossa chamada), para guardar movimentos reais sem duplicar o mesmo preço.
    material = "|".join((
        observation_id,
        str(provenance.get("source") or ""),
        bookmaker,
        str(provenance.get("event_id") or ""),
        str(provenance.get("provider_timestamp") or ""),
        str(provenance.get("raw_payload_sha256") or ""),
        f"{odd_a:.6f}",
        f"{odd_b:.6f}",
    ))
    shadow = observation.get("contextual_shadow") or {}
    return {
        "schema_version": 1,
        "market_observation_id": hashlib.sha256(
            material.encode(),
        ).hexdigest()[:32],
        "observation_id": observation_id,
        "canonical_match_instance_id": observation.get(
            "canonical_match_instance_id"
        ),
        "model_version": model_version,
        "configuration_fingerprint": shadow.get("configuration_fingerprint"),
        "prediction_analyzed_at_utc": observation.get("analyzed_at_utc"),
        "captured_at_utc": captured.isoformat(timespec="seconds"),
        "commence_time_utc": observation.get("commence_time_utc"),
        "source": provenance.get("source"),
        "endpoint": provenance.get("endpoint"),
        "event_id": provenance.get("event_id"),
        "bookmaker": bookmaker,
        "provider_timestamp": provenance.get("provider_timestamp"),
        "raw_payload_sha256": provenance.get("raw_payload_sha256"),
        "identity_linkage": "EXACT_PLAYER_IDS_TOUR_AND_TIME",
        "odds": {"a": round(odd_a, 6), "b": round(odd_b, 6)},
        "market_probability_devig": {
            "a": round(probability_a, 8),
            "b": round(probability_b, 8),
        },
        "overround": round(overround, 8),
        "first_valid_quote_frozen": True,
        "immutable_quote_snapshot": True,
        "paper_eligible": False,
        "green_eligible": False,
        "production_effect": False,
    }


def read_markets(path: Path = MARKET_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1,
    ):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid market JSONL at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"invalid market row at {path}:{line_number}")
        rows.append(row)
    return rows


def append_markets(
    rows: Iterable[Mapping[str, Any]], path: Path = MARKET_PATH,
) -> int:
    """Append immutable quote snapshots without rewriting earlier prices."""
    existing_rows = read_markets(path)
    existing = {
        str(row.get("market_observation_id")): row for row in existing_rows
        if row.get("market_observation_id")
    }
    additions = []
    for source in rows:
        row = dict(source)
        if not row.get("observation_id"):
            raise ValueError("market observation without observation_id")
        key = str(row.get("market_observation_id") or "")
        if not key:
            raise ValueError("market observation without market_observation_id")
        if key in existing:
            continue
        if row.get("first_valid_quote_frozen") is not True:
            raise ValueError("market observation is not frozen")
        existing[key] = row
        additions.append(row)
    if additions:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(
                    row, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)
