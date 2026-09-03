"""Market-Time Ledger append-only para observacoes Moneyline ja recolhidas.

O ledger e deliberadamente best effort: uma falha de persistencia nunca muda
pricing, decisao ou PAPER. Os consumidores devem tratar um resultado sem
``entry_observation_id`` como nao elegivel para Market Memory/CLV.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .pricing import de_vig_market_probabilities


SCHEMA_VERSION = 1
DEFAULT_ROOT = Path("data/market_ledger")
try:
    DEFAULT_RETENTION_DAYS = int(os.environ.get("MARKET_LEDGER_ACTIVE_DAYS", "45"))
except (TypeError, ValueError):
    # Configuração inválida desta camada auxiliar nunca impede o bot.
    DEFAULT_RETENTION_DAYS = 45
CHANGE_ID = "CHANGE-2026-09-03-024"
_LOCK = threading.RLock()
_DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")


class MarketLedgerError(RuntimeError):
    """Erro explicito de validacao, leitura ou persistencia do ledger."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def payload_sha256(value: Any) -> str:
    """Hash estavel de um payload ja presente em memoria; nao faz I/O."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_utc(value: Any, *, field: str) -> datetime:
    if value in (None, ""):
        raise MarketLedgerError(f"missing_{field}")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MarketLedgerError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: Any, *, field: str) -> str:
    return _parse_utc(value, field=field).isoformat(timespec="seconds")


def _player(match: Mapping[str, Any], side: str) -> dict[str, Any]:
    number = "1" if side == "a" else "2"
    nested = match.get(f"player{number}")
    nested = nested if isinstance(nested, Mapping) else {}
    return {
        "id": match.get(f"player_{side}_id", match.get(f"player{number}Id", nested.get("id"))),
        "name": str(match.get(f"player_{side}") or nested.get("name") or "").strip(),
    }


def event_key(match: Mapping[str, Any]) -> str:
    """Identidade partilhada por ledger, snapshot e PAPER."""
    tour = str(match.get("tour") or match.get("_tour") or "unknown").strip().lower()
    match_id = match.get("match_id", match.get("id"))
    if match_id not in (None, ""):
        return f"{tour}:{match_id}"
    player_a, player_b = _player(match, "a"), _player(match, "b")
    material = {
        "tour": tour,
        "player_ids": sorted(str(item) for item in (player_a.get("id"), player_b.get("id")) if item not in (None, "")),
        "player_names": sorted((player_a["name"].casefold(), player_b["name"].casefold())),
        "scheduled_start_utc": match.get("commence_time_utc") or match.get("date"),
        "tournament_id": match.get("tournament_id", match.get("tournamentId")),
    }
    return "fallback:" + payload_sha256(material)[:24]


def _odd_for_side(odds: Mapping[str, Any], player: Mapping[str, Any], side: str) -> float:
    candidates = (f"player_{side}", side, player.get("name"))
    value = None
    for candidate in candidates:
        if candidate in odds:
            value = odds[candidate]
            break
        for key, candidate_value in odds.items():
            if str(key).casefold() == str(candidate or "").casefold():
                value = candidate_value
                break
        if value is not None:
            break
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketLedgerError(f"invalid_odd_{side}") from exc
    if not math.isfinite(parsed) or parsed <= 1:
        raise MarketLedgerError(f"invalid_odd_{side}")
    return parsed


def _provider_name(source: Any) -> str:
    text = str(source or "").strip()
    folded = text.casefold()
    if "rapidapi" in folded:
        return "RapidAPI"
    if "odds api" in folded:
        return "The Odds API"
    return text or "UNKNOWN"


def build_observation(
    match: Mapping[str, Any],
    odds: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    role: str,
    pipeline: str,
    raw_payload: Any = None,
) -> dict[str, Any]:
    """Normaliza uma observacao ja recolhida, sem consultar qualquer API."""
    player_a, player_b = _player(match, "a"), _player(match, "b")
    if not player_a["name"] or not player_b["name"]:
        raise MarketLedgerError("missing_player_identity")
    scheduled = _utc_text(
        match.get("commence_time_utc") or match.get("date"),
        field="scheduled_start_utc",
    )
    captured = _utc_text(provenance.get("captured_at_utc"), field="captured_at_utc")
    odd_a = _odd_for_side(odds, player_a, "a")
    odd_b = _odd_for_side(odds, player_b, "b")
    probability_a, probability_b, overround = de_vig_market_probabilities(odd_a, odd_b)

    provider_timestamp = provenance.get("provider_timestamp")
    provider_timestamp_utc = None
    if provider_timestamp not in (None, ""):
        try:
            provider_timestamp_utc = _utc_text(provider_timestamp, field="provider_timestamp")
        except MarketLedgerError:
            provider_timestamp_utc = None

    raw_hash = str(provenance.get("raw_payload_sha256") or "").strip()
    identifier_kind = "RAW_PAYLOAD_SHA256"
    if not raw_hash:
        # Algumas fontes embutidas nao conservam o envelope HTTP completo.
        # O equivalente abaixo identifica canonicamente a parcela factual
        # efetivamente usada, sem inventar um payload que ja nao existe.
        raw_hash = payload_sha256(raw_payload if raw_payload is not None else {
            "odds": dict(odds),
            "source": provenance.get("source"),
            "endpoint": provenance.get("endpoint"),
            "event_id": provenance.get("event_id"),
            "bookmaker": provenance.get("bookmaker"),
            "provider_timestamp": provider_timestamp,
            "captured_at_utc": captured,
        })
        identifier_kind = "CANONICAL_SOURCE_FRAGMENT_SHA256"

    capture_dt = _parse_utc(captured, field="captured_at_utc")
    start_dt = _parse_utc(scheduled, field="scheduled_start_utc")
    prestart_status = "PRESTART" if capture_dt < start_dt else "NOT_PRESTART"
    bookmaker = provenance.get("bookmaker")
    bookmaker_status = "IDENTIFIED" if bookmaker else "UNAVAILABLE"
    mapping_status = str(provenance.get("identity_mapping_status") or "VERIFIED").upper()
    freshness_status = str(
        provenance.get("freshness_status")
        or ("OBSERVED_AT_CAPTURE" if provenance.get("capture_kind") else "UNKNOWN")
    ).upper()
    clv_eligible = (
        prestart_status == "PRESTART"
        and bookmaker_status == "IDENTIFIED"
        and mapping_status == "VERIFIED"
        and freshness_status not in {"STALE", "UNKNOWN", "UNAVAILABLE"}
    )
    ineligible_reasons = []
    if prestart_status != "PRESTART":
        ineligible_reasons.append("NOT_PRESTART")
    if bookmaker_status != "IDENTIFIED":
        ineligible_reasons.append("BOOKMAKER_UNAVAILABLE")
    if mapping_status != "VERIFIED":
        ineligible_reasons.append("IDENTITY_MAPPING_UNVERIFIED")
    if freshness_status in {"STALE", "UNKNOWN", "UNAVAILABLE"}:
        ineligible_reasons.append(f"FRESHNESS_{freshness_status}")

    observation = {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "record_type": "MARKET_OBSERVATION",
        "event": {
            "event_key": event_key(match),
            "match_id": match.get("match_id", match.get("id")),
            "provider_event_id": provenance.get("event_id"),
            "tour": match.get("tour") or match.get("_tour"),
            "tournament_id": match.get("tournament_id", match.get("tournamentId")),
            "tournament": match.get("tournament") or match.get("tournament_name"),
            "scheduled_start_utc": scheduled,
            "player_a": player_a,
            "player_b": player_b,
        },
        "market": {"type": "MONEYLINE", "period": "FULL_TIME", "two_way": True},
        "source": {
            "provider": _provider_name(provenance.get("source")),
            "source_name": provenance.get("source"),
            "endpoint": provenance.get("endpoint"),
            "bookmaker": bookmaker,
            "bookmaker_status": bookmaker_status,
            "role": role,
        },
        "capture": {
            "captured_at_utc": captured,
            "provider_timestamp_utc": provider_timestamp_utc,
            "provider_timestamp_status": provenance.get("provider_timestamp_status") or (
                "AVAILABLE" if provider_timestamp_utc else "UNAVAILABLE"
            ),
            "freshness_status": freshness_status,
            "freshness_basis": provenance.get("capture_kind"),
            "from_cache": bool(provenance.get("from_cache")),
            "cache_age_seconds": provenance.get("cache_age_seconds"),
            "prestart_status": prestart_status,
            "identity_mapping_status": mapping_status,
            "pipeline": pipeline,
            "github_run_id": provenance.get("github_run_id") or os.environ.get("GITHUB_RUN_ID"),
        },
        "selections": [
            {
                "side": "a", "player_id": player_a.get("id"), "name": player_a["name"],
                "provider_side": provenance.get("provider_side_a"),
                "raw_decimal_odd": odd_a, "raw_implied_probability": 1.0 / odd_a,
                "devig_probability": probability_a,
            },
            {
                "side": "b", "player_id": player_b.get("id"), "name": player_b["name"],
                "provider_side": provenance.get("provider_side_b"),
                "raw_decimal_odd": odd_b, "raw_implied_probability": 1.0 / odd_b,
                "devig_probability": probability_b,
            },
        ],
        "overround": overround,
        "eligibility": {
            "market_memory": clv_eligible,
            "clv": clv_eligible,
            "reasons": ineligible_reasons,
        },
        "provenance": {
            "raw_payload_sha256": raw_hash,
            "provenance_identifier_kind": identifier_kind,
        },
    }
    immutable_material = dict(observation)
    observation_id = payload_sha256(immutable_material)
    observation["observation_id"] = observation_id
    observation["provenance"]["canonical_observation_sha256"] = observation_id
    return observation


def _active_path(root: Path, captured_at_utc: str) -> Path:
    return root / "observations" / f"{captured_at_utc[:10]}.jsonl"


def _archive_path(root: Path, day: str) -> Path:
    year, month, _ = day.split("-")
    return root / "archive" / year / month / f"{day}.jsonl.gz"


def _ids_in_file(path: Path, *, compressed: bool = False) -> set[str]:
    if not path.exists():
        return set()
    opener = gzip.open if compressed else Path.open
    try:
        handle = opener(path, "rt", encoding="utf-8") if compressed else opener(path, "r", encoding="utf-8")
        with handle:
            ids = set()
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MarketLedgerError(f"corrupt_jsonl:{path}:{line_number}") from exc
                if value.get("observation_id"):
                    ids.add(str(value["observation_id"]))
            return ids
    except OSError as exc:
        raise MarketLedgerError(f"unreadable_ledger:{path}") from exc


def append_observation(observation: Mapping[str, Any], *, root: Path = DEFAULT_ROOT) -> bool:
    """Acrescenta uma linha; ``False`` significa retry/duplicado idempotente."""
    observation_id = str(observation.get("observation_id") or "")
    captured = str((observation.get("capture") or {}).get("captured_at_utc") or "")
    if not observation_id or not captured:
        raise MarketLedgerError("invalid_observation_envelope")
    path = _active_path(root, captured)
    archive = _archive_path(root, captured[:10])
    with _LOCK:
        if observation_id in _ids_in_file(path):
            return False
        if archive.exists():
            if observation_id in _ids_in_file(archive, compressed=True):
                return False
            raise MarketLedgerError("capture_day_already_archived")
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = _canonical_json(dict(observation)) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    return True


def record_market_batch_best_effort(
    match: Mapping[str, Any],
    odds: Mapping[str, Any] | None,
    provenance: Mapping[str, Any] | None,
    *,
    role: str,
    pipeline: str,
    root: Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Persiste todas as quotes ja obtidas e nunca propaga falhas ao pipeline."""
    if not odds or not provenance:
        return {"status": "UNAVAILABLE", "entry_observation_id": None, "observation_ids": [], "errors": []}
    raw_quotes = provenance.get("market_quotes")
    quotes = list(raw_quotes) if isinstance(raw_quotes, list) and raw_quotes else [{
        "odds": dict(odds),
        "bookmaker": provenance.get("bookmaker"),
        "provider_timestamp": provenance.get("provider_timestamp"),
        "raw_payload_sha256": provenance.get("raw_payload_sha256"),
        "provider_side_a": provenance.get("provider_side_a"),
        "provider_side_b": provenance.get("provider_side_b"),
    }]
    ids: list[str] = []
    errors: list[str] = []
    selected_id = None
    selected_eligible = False
    selected_bookmaker = str(provenance.get("bookmaker") or "")
    for quote in quotes:
        if not isinstance(quote, Mapping):
            continue
        quote_odds = quote.get("odds")
        if not isinstance(quote_odds, Mapping):
            continue
        quote_provenance = dict(provenance)
        quote_provenance.pop("market_quotes", None)
        for key in (
            "bookmaker", "provider_timestamp", "provider_timestamp_status",
            "freshness_status", "raw_payload_sha256", "provider_side_a", "provider_side_b",
            "identity_mapping_status",
        ):
            if key in quote:
                quote_provenance[key] = quote.get(key)
        try:
            observation = build_observation(
                match, quote_odds, quote_provenance, role=role, pipeline=pipeline,
            )
            append_observation(observation, root=root)
            observation_id = observation["observation_id"]
            ids.append(observation_id)
            if str(quote_provenance.get("bookmaker") or "") == selected_bookmaker and dict(quote_odds) == dict(odds):
                selected_id = observation_id
                selected_eligible = bool((observation.get("eligibility") or {}).get("market_memory"))
        except Exception as exc:  # best effort por contrato; erro fica observavel
            errors.append(f"{type(exc).__name__}:{exc}")
    if selected_id is None:
        errors.append("selected_entry_observation_not_persisted")
    return {
        "status": "RECORDED" if ids and not errors else "PARTIAL" if ids else "INELIGIBLE",
        "entry_observation_id": selected_id,
        "entry_memory_eligible": selected_eligible,
        "observation_ids": ids,
        "errors": errors,
    }


def rotate_archives(
    *,
    root: Path = DEFAULT_ROOT,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    today: date | None = None,
) -> list[str]:
    """Comprime dias fechados antigos sem reescrever arquivos existentes."""
    if retention_days < 1:
        raise MarketLedgerError("retention_days_must_be_positive")
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=retention_days)
    archived: list[str] = []
    observations_dir = root / "observations"
    if not observations_dir.exists():
        return archived
    with _LOCK:
        for source in sorted(observations_dir.glob("*.jsonl")):
            match = _DAY_RE.match(source.name)
            if not match:
                continue
            day = date.fromisoformat(match.group(1))
            if day >= cutoff:
                continue
            destination = _archive_path(root, match.group(1))
            if destination.exists():
                continue
            source_bytes = source.read_bytes()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
            try:
                with temp.open("wb") as raw_handle:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
                        zipped.write(source_bytes)
                    raw_handle.flush()
                    os.fsync(raw_handle.fileno())
                if gzip.decompress(temp.read_bytes()) != source_bytes:
                    raise MarketLedgerError(f"archive_verification_failed:{source.name}")
                # Hard-link com semantica create-only: mesmo numa corrida
                # entre processos, um arquivo existente nunca e substituido.
                try:
                    os.link(temp, destination)
                except FileExistsError:
                    continue
                temp.unlink()
                source.unlink()
                archived.append(match.group(1))
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
    return archived


def read_observations(*, root: Path = DEFAULT_ROOT) -> list[dict[str, Any]]:
    """Le o ledger ativo e o arquivo; corrupcao e explicita, nunca ignorada."""
    paths: list[tuple[Path, bool]] = []
    active = root / "observations"
    archive = root / "archive"
    if active.exists():
        paths.extend((path, False) for path in sorted(active.glob("*.jsonl")))
    if archive.exists():
        paths.extend((path, True) for path in sorted(archive.rglob("*.jsonl.gz")))
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, compressed in paths:
        opener = gzip.open if compressed else Path.open
        handle = opener(path, "rt", encoding="utf-8") if compressed else opener(path, "r", encoding="utf-8")
        with handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MarketLedgerError(f"corrupt_jsonl:{path}:{line_number}") from exc
                observation_id = str(value.get("observation_id") or "")
                if not observation_id:
                    raise MarketLedgerError(f"missing_observation_id:{path}:{line_number}")
                if observation_id not in seen:
                    values.append(value)
                    seen.add(observation_id)
    return sorted(values, key=lambda item: ((item.get("capture") or {}).get("captured_at_utc") or "", item["observation_id"]))


def observation_by_id(observation_id: Any, *, root: Path = DEFAULT_ROOT) -> dict[str, Any] | None:
    wanted = str(observation_id or "")
    if not wanted:
        return None
    return next((item for item in read_observations(root=root) if item.get("observation_id") == wanted), None)


def selection_for_side(observation: Mapping[str, Any], side: str) -> Mapping[str, Any] | None:
    return next(
        (item for item in observation.get("selections") or [] if str(item.get("side")).casefold() == str(side).casefold()),
        None,
    )


def last_comparable_prestart(
    pregame: Mapping[str, Any],
    *,
    root: Path = DEFAULT_ROOT,
    require_later_than_entry: bool = True,
) -> dict[str, Any] | None:
    """Escolhe a ultima quote pre-start da mesma fonte/casa da entrada."""
    event = str(pregame.get("event_key") or pregame.get("snapshot_key") or "")
    entry_id = pregame.get("entry_market_observation_id")
    entry = observation_by_id(entry_id, root=root)
    if not event or not entry or not (entry.get("eligibility") or {}).get("clv"):
        return None
    start = _parse_utc(pregame.get("commence_time_utc"), field="scheduled_start_utc")
    entry_capture = _parse_utc((entry.get("capture") or {}).get("captured_at_utc"), field="captured_at_utc")
    entry_source = entry.get("source") or {}
    candidates = []
    for observation in read_observations(root=root):
        source = observation.get("source") or {}
        if str((observation.get("event") or {}).get("event_key")) != event:
            continue
        if not (observation.get("eligibility") or {}).get("clv"):
            continue
        observation_start = _parse_utc(
            (observation.get("event") or {}).get("scheduled_start_utc"),
            field="scheduled_start_utc",
        )
        if observation_start != start:
            # Uma remarcacao cria uma serie temporal distinta para efeitos de
            # closing; nunca misturamos silenciosamente cutoffs diferentes.
            continue
        if (
            source.get("provider") != entry_source.get("provider")
            or source.get("source_name") != entry_source.get("source_name")
            or source.get("endpoint") != entry_source.get("endpoint")
            or source.get("bookmaker") != entry_source.get("bookmaker")
        ):
            continue
        captured = _parse_utc((observation.get("capture") or {}).get("captured_at_utc"), field="captured_at_utc")
        if captured >= start or (require_later_than_entry and captured <= entry_capture):
            continue
        candidates.append((captured, observation))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def clv_for_pregame(pregame: Mapping[str, Any], *, root: Path = DEFAULT_ROOT) -> dict[str, Any] | None:
    """CLV do lado PAPER; positivo significa mercado a mover-se para o lado."""
    side = str(pregame.get("selected_side") or "").casefold()
    entry = observation_by_id(pregame.get("entry_market_observation_id"), root=root)
    closing = last_comparable_prestart(pregame, root=root)
    if side not in {"a", "b"} or not entry or not closing:
        return None
    entry_selection = selection_for_side(entry, side)
    closing_selection = selection_for_side(closing, side)
    if not entry_selection or not closing_selection:
        return None
    entry_probability = float(entry_selection["devig_probability"])
    closing_probability = float(closing_selection["devig_probability"])
    entry_odd = float(entry_selection["raw_decimal_odd"])
    closing_odd = float(closing_selection["raw_decimal_odd"])
    probability_pp = (closing_probability - entry_probability) * 100.0
    price_pct = (entry_odd / closing_odd - 1.0) * 100.0
    return {
        "entry_market_observation_id": entry["observation_id"],
        "closing_market_observation_id": closing["observation_id"],
        "entry_market_probability": round(entry_probability, 8),
        "last_valid_prestart_market_probability": round(closing_probability, 8),
        "closing_odd": closing_odd,
        "clv_probability_pp": round(probability_pp, 4),
        "clv_price_pct": round(price_pct, 4),
        # Campo legado passa a representar a metrica primaria documentada.
        "clv_pct": round(probability_pp, 4),
    }
