"""Compact public index used to link manual PAPER rows to generated reports.

The index contains only information that is already public in the report
dashboard.  It deliberately does not contain manual selections, stakes,
results or notes from the private Google Sheet.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

from . import round_stage


SCHEMA_VERSION = 1
DEFAULT_OUTPUT_PATH = Path("data/validation/manual-paper-linkage-index-v1.json")
FACTOR_INDEX_SCHEMA_VERSION = 5
DEFAULT_FACTOR_OUTPUT_PATH = Path("data/validation/manual-paper-factor-index-v1.json")

_ROUND_RECOVERY_MAX_DISTANCE_SECONDS = 3 * 24 * 60 * 60


_WEIGHT_ROW_START = re.compile(
    r'<div class="weight-row(?:\s+inactive)?" data-weight-factor="([^"]+)">',
)


def _legacy_report_factor_record(
    content: str, player_a: str, player_b: str,
) -> dict[str, Any] | None:
    """Recover frozen public factor facts from a legacy pre-match report."""
    starts = list(_WEIGHT_ROW_START.finditer(content))
    factors: list[list[Any]] = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(content)
        block = content[match.start():end]
        direction_match = re.search(r'class="weight-state\s+([ab])"', block)
        weight_match = re.search(
            r'class="weight-number used">\s*([0-9]+(?:[.,][0-9]+)?)\s*<', block,
        )
        if not direction_match or not weight_match:
            continue
        weight = float(weight_match.group(1).replace(",", "."))
        if weight <= 0:
            continue
        factors.append([html.unescape(match.group(1)), direction_match.group(1), round(weight, 3)])
    if not factors:
        return None

    tour_match = re.search(r'class="mh-sub(?:\s+b)?">\s*(ATP|WTA)\b', content, re.I)
    context_match = re.search(
        r'class="mh-tourn">.*?<br>\s*(ATP|WTA)\s*([^<·Â]*?)\s*(?:Â?·)\s*([^<]+)</div>',
        content,
        re.I | re.S,
    )
    index_values = [
        float(value)
        for value in re.findall(
            r'class="mvs-val"[^>]*>\s*([0-9]+(?:\.[0-9]+)?)/100\s*</div>',
            content,
        )[:2]
    ]
    index_a = index_values[0] if len(index_values) == 2 else None
    index_b = index_values[1] if len(index_values) == 2 else None
    model_side = None
    if index_a is not None and index_b is not None and index_a != index_b:
        model_side = "a" if index_a > index_b else "b"
    tour = (context_match or tour_match).group(1).upper() if (context_match or tour_match) else None
    return {
        "t": tour,
        "l": html.unescape(context_match.group(2).strip()) if context_match else None,
        "s": html.unescape(context_match.group(3).strip()) if context_match else None,
        "a": player_a,
        "b": player_b,
        "m": model_side,
        "ia": index_a,
        "ib": index_b,
        "p": None,
        "me": None,
        "mc": None,
        "f": factors,
        "o": "REPORT_HTML_RECONSTRUCTED",
    }


def build_legacy_report_factor_records(
    dashboard: Mapping[str, Any], reports_root: Path,
    player_cache_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Build factor records for public reports created before snapshots existed."""
    records: dict[str, dict[str, Any]] = {}
    round_evidence = (
        build_cached_round_evidence(player_cache_root)
        if player_cache_root is not None else {}
    )
    for day_value in dashboard.get("days") or []:
        day = _mapping(day_value)
        reports = [row for row in day.get("reports") or [] if isinstance(row, Mapping)]
        for matchup_value in day.get("matchups") or []:
            matchup = _mapping(matchup_value)
            match_key = str(matchup.get("match_key") or "").strip()
            player_a, player_b = _split_title(matchup.get("title"))
            if not match_key or not player_a or not player_b or match_key in records:
                continue
            versions = [
                reports[index]
                for index in matchup.get("version_indexes") or []
                if isinstance(index, int) and 0 <= index < len(reports)
            ]
            representative = next(
                (row for row in versions if row.get("linkage") == "EXACT_REPORT_ID"),
                versions[0] if versions else {},
            )
            filename = Path(str(representative.get("url") or "")).name
            if not filename.lower().endswith(".html"):
                continue
            report_path = reports_root / filename
            try:
                content = report_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            record = _legacy_report_factor_record(content, player_a, player_b)
            if record:
                record["r"] = recover_round_stage_by_names(
                    tour=record.get("t"),
                    player_a=player_a,
                    player_b=player_b,
                    report_date=day.get("date"),
                    evidence=round_evidence,
                )
                records[match_key] = record
    return records


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _name_token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    ascii_text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _player_cache_recent_matches(
    cache_root: Path, tour: str, player_id: Any,
) -> list[Mapping[str, Any]]:
    try:
        path = cache_root / tour / f"{int(player_id)}.json"
    except (TypeError, ValueError):
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    entry = _mapping(_mapping(document.get("entries")).get("recent_matches"))
    return [row for row in entry.get("data") or [] if isinstance(row, Mapping)]


def build_cached_round_evidence(
    cache_root: Path,
) -> dict[tuple[str, tuple[str, str]], list[tuple[float, int]]]:
    """Index factual cached rounds by tour and exact player pair."""
    evidence: dict[tuple[str, tuple[str, str]], set[tuple[float, int]]] = {}
    for tour in ("atp", "wta"):
        tour_root = cache_root / tour
        try:
            paths = sorted(tour_root.glob("*.json"))
        except OSError:
            paths = []
        for path in paths:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            entry = _mapping(_mapping(document.get("entries")).get("recent_matches"))
            for match in entry.get("data") or []:
                if not isinstance(match, Mapping):
                    continue
                players = tuple(sorted((
                    _name_token(_mapping(match.get("player1")).get("name")),
                    _name_token(_mapping(match.get("player2")).get("name")),
                )))
                match_time = _timestamp(match.get("date"))
                try:
                    round_id = int(match.get("roundId"))
                except (TypeError, ValueError):
                    continue
                if (
                    not all(players)
                    or match_time is None
                    or round_stage.classify_round_stage(round_id=round_id)
                    == round_stage.UNRESOLVED
                ):
                    continue
                evidence.setdefault((tour, players), set()).add((match_time, round_id))
    return {key: sorted(values) for key, values in evidence.items()}


def recover_round_stage_by_names(
    *, tour: Any, player_a: Any, player_b: Any, report_date: Any,
    evidence: Mapping[tuple[str, tuple[str, str]], list[tuple[float, int]]],
) -> str:
    """Recover a legacy report stage only from one unambiguous cached match."""
    target_time = _timestamp(f"{report_date}T12:00:00+00:00")
    players = tuple(sorted((_name_token(player_a), _name_token(player_b))))
    key = (str(tour or "").strip().lower(), players)
    if target_time is None or not all(players) or key[0] not in {"atp", "wta"}:
        return round_stage.UNRESOLVED
    recovered = {
        round_stage.classify_round_stage(round_id=round_id)
        for match_time, round_id in evidence.get(key, [])
        if abs(match_time - target_time) <= _ROUND_RECOVERY_MAX_DISTANCE_SECONDS
    }
    recovered.discard(round_stage.UNRESOLVED)
    return next(iter(recovered)) if len(recovered) == 1 else round_stage.UNRESOLVED


def recover_round_id_from_player_cache(
    snapshot: Mapping[str, Any], cache_root: Path,
    recent_cache: dict[tuple[str, str], list[Mapping[str, Any]]] | None = None,
) -> int | None:
    """Recover a missing provider round from the canonical player caches.

    Old snapshots did not persist ``round_id``.  Their player caches still
    contain the completed match with both player IDs, tournament ID, date and
    provider round.  Recovery is accepted only when all those identity fields
    agree and every matching cache record reports the same round.  Ambiguous
    evidence stays unresolved.
    """
    tour = str(snapshot.get("tour") or "").strip().lower()
    if tour not in {"atp", "wta"}:
        return None
    player_ids = {
        str(_mapping(snapshot.get("player_a")).get("id") or "").strip(),
        str(_mapping(snapshot.get("player_b")).get("id") or "").strip(),
    }
    if "" in player_ids or len(player_ids) != 2:
        return None
    tournament_id = str(snapshot.get("tournament_id") or "").strip()
    target_time = _timestamp(
        snapshot.get("commence_time_utc") or snapshot.get("analyzed_at_utc")
    )
    if not tournament_id or target_time is None:
        return None

    recovered: set[int] = set()
    recent_cache = recent_cache if recent_cache is not None else {}
    for player_id in player_ids:
        cache_key = (tour, player_id)
        if cache_key not in recent_cache:
            recent_cache[cache_key] = _player_cache_recent_matches(
                cache_root, tour, player_id,
            )
        for match in recent_cache[cache_key]:
            match_player_ids = {
                str(match.get("player1Id") or "").strip(),
                str(match.get("player2Id") or "").strip(),
            }
            match_tournament_id = str(
                match.get("tournamentId")
                or _mapping(match.get("tournament")).get("id")
                or ""
            ).strip()
            match_time = _timestamp(match.get("date"))
            if (
                match_player_ids != player_ids
                or match_tournament_id != tournament_id
                or match_time is None
                or abs(match_time - target_time) > _ROUND_RECOVERY_MAX_DISTANCE_SECONDS
            ):
                continue
            stage = round_stage.classify_round_stage(round_id=match.get("roundId"))
            if stage == round_stage.UNRESOLVED:
                continue
            try:
                recovered.add(int(match.get("roundId")))
            except (TypeError, ValueError):
                continue
    return next(iter(recovered)) if len(recovered) == 1 else None


def _split_title(title: Any) -> tuple[str | None, str | None]:
    parts = str(title or "").split(" vs ", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return None, None
    return parts[0].strip(), parts[1].strip()


def build_index(
    dashboard: Mapping[str, Any], snapshots: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshots = snapshots or []
    snapshot_by_report = {
        str(row.get("report_id")): row
        for row in snapshots
        if row.get("report_id") and row.get("key")
    }
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for day in dashboard.get("days") or []:
        day = _mapping(day)
        report_date = str(day.get("date") or "")
        reports = [row for row in day.get("reports") or [] if isinstance(row, Mapping)]
        for matchup_value in day.get("matchups") or []:
            matchup = _mapping(matchup_value)
            title = str(matchup.get("title") or "").strip()
            player_a, player_b = _split_title(title)
            if not report_date or not player_a or not player_b:
                continue
            identity = (report_date, title.casefold())
            if identity in seen:
                continue
            seen.add(identity)

            versions = []
            for index in matchup.get("version_indexes") or []:
                if isinstance(index, int) and 0 <= index < len(reports):
                    versions.append(reports[index])
            representative = next(
                (row for row in versions if row.get("linkage") == "EXACT_REPORT_ID"),
                versions[0] if versions else {},
            )
            snapshot = snapshot_by_report.get(str(representative.get("report_id") or ""))
            record = {
                "report_date": report_date,
                "player_a": player_a,
                "player_b": player_b,
                "report_match_key": matchup.get("match_key"),
                "linkage_source": matchup.get("match_key_source"),
                "report_url": urljoin(
                    "https://sharp-signals.github.io/Tennis/dashboard/",
                    str(representative.get("url") or ""),
                ) if representative.get("url") else None,
                "snapshot_key": snapshot.get("key") if snapshot else None,
                "commence_time_utc": (
                    snapshot.get("commence_time_utc") if snapshot
                    else matchup.get("scheduled_start_utc")
                ),
            }
            records.append(record)

    records.sort(key=lambda row: (
        str(row.get("report_date") or ""),
        str(row.get("player_a") or "").casefold(),
        str(row.get("player_b") or "").casefold(),
    ))
    material = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy_contract": "PUBLIC_REPORT_IDENTITY_ONLY_NO_MANUAL_SELECTIONS",
        "record_count": len(records),
        "fingerprint_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "records": records,
    }


def write_index(document: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Compact serialization minimizes repository/API payloads. Consumers accept
    # both inline Contents API data and download_url for files above 1 MB.
    # Apps Script consumes the file through that endpoint and therefore needs
    # the response body to contain Base64 data rather than a download URL.
    content = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ) + "\n"
    path.write_text(content, encoding="utf-8")


def build_factor_index(
    snapshots: list[Mapping[str, Any]] | None = None,
    market_memory: Mapping[str, Any] | None = None,
    legacy_report_factors: Mapping[str, Mapping[str, Any]] | None = None,
    player_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Build a compact, public lookup for private Sheet-side aggregation.

    The Google Sheet already knows which report/snapshot belongs to each
    manual PAPER row.  This lookup exposes only facts already present in the
    public report: players, tour, surface, Fenzobot side/index and active
    factor directions/weights.  Apps Script joins those facts privately and
    publishes aggregates only; individual manual selections never enter this
    document or the repository.
    """
    market_by_snapshot = {
        str(row.get("snapshot_key")): row
        for row in (market_memory or {}).get("events") or []
        if isinstance(row, Mapping) and row.get("snapshot_key")
    }
    records: dict[str, dict[str, Any]] = {}
    recent_round_cache: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    ordered = sorted(
        (row for row in (snapshots or []) if isinstance(row, Mapping)),
        key=lambda row: str(row.get("analyzed_at_utc") or ""),
    )
    for snapshot in ordered:
        key = str(snapshot.get("key") or "").strip()
        if not key or key in records:
            continue
        metrics = _mapping(snapshot.get("metrics"))
        divergence = _mapping(metrics.get("divergencia"))
        statuses = _mapping(divergence.get("fatores_status"))
        if not statuses:
            continue
        factors: list[list[Any]] = []
        for factor, raw_status in sorted(statuses.items()):
            status = _mapping(raw_status)
            direction = str(status.get("direcao_impacto") or "").strip().casefold()
            try:
                weight = float(status.get("peso_efetivo") or 0)
            except (TypeError, ValueError):
                weight = 0.0
            if direction not in {"a", "b"} or weight <= 0:
                continue
            factors.append([str(factor), direction, round(weight, 3)])
        player_a = _mapping(snapshot.get("player_a"))
        player_b = _mapping(snapshot.get("player_b"))
        name_a = str(player_a.get("name") or "").strip()
        name_b = str(player_b.get("name") or "").strip()
        favoured = str(divergence.get("indice_favorece") or "").strip().casefold()
        model_side = "a" if favoured == name_a.casefold() else "b" if favoured == name_b.casefold() else None
        pricing = _mapping(snapshot.get("pricing"))
        sharp = {
            side: pricing.get(f"sharp_estimate_{side}")
            for side in ("a", "b")
        }
        market_row = _mapping(market_by_snapshot.get(key))
        entry_market = _mapping(market_row.get("entry_market_probabilities"))
        closing_market = _mapping(
            market_row.get("last_valid_prestart_market_probabilities")
        )

        def probability_pair(values: Mapping[str, Any]) -> list[float] | None:
            try:
                pair = [float(values["a"]), float(values["b"])]
            except (KeyError, TypeError, ValueError):
                return None
            if not all(0 < value < 1 for value in pair):
                return None
            return [round(value, 8) for value in pair]

        direct_round_id = (
            snapshot.get("round_id")
            or _mapping(snapshot.get("identity_evidence")).get("round_id")
        )
        round_label = snapshot.get("round")
        round_value = round_stage.classify_round_stage(
            round_id=direct_round_id,
            round_label=round_label,
        )
        if round_value == round_stage.UNRESOLVED and player_cache_root is not None:
            recovered_round_id = recover_round_id_from_player_cache(
                snapshot, player_cache_root, recent_round_cache,
            )
            if recovered_round_id is not None:
                round_value = round_stage.classify_round_stage(
                    round_id=recovered_round_id,
                )

        records[key] = {
            # Short field names keep the GitHub Contents response comfortably
            # below its inline-content boundary without reducing semantics.
            "t": str(snapshot.get("tour") or "").strip().upper() or None,
            "l": str(snapshot.get("tier") or "").strip() or None,
            "s": str(snapshot.get("surface") or "").strip() or None,
            "a": name_a or None,
            "b": name_b or None,
            "m": model_side,
            "ia": divergence.get("indice_evidencia_a"),
            "ib": divergence.get("indice_evidencia_b"),
            # Probabilidades congeladas no snapshot. Permitem calcular na
            # Sheet o edge da odd realmente executada, sem publicar a aposta.
            "p": probability_pair(sharp),
            # Entry/closing do mercado de referência já validados pelo ledger
            # como comparáveis. Não representam necessariamente a casa usada
            # na execução manual e, por isso, nunca são rotulados como CLV.
            "me": probability_pair(entry_market),
            "mc": probability_pair(closing_market),
            "r": round_value,
            "f": factors,
        }
    for key, raw_record in sorted((legacy_report_factors or {}).items()):
        if key and key not in records and isinstance(raw_record, Mapping):
            records[str(key)] = dict(raw_record)
    material = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": FACTOR_INDEX_SCHEMA_VERSION,
        "privacy_contract": "PUBLIC_REPORT_FACTS_ONLY_NO_MANUAL_SELECTIONS",
        "record_count": len(records),
        "fingerprint_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "records": records,
    }
