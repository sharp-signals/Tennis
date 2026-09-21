"""Gate deterministico de integridade para mercados Moneyline de duas vias."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping


CHANGE_ID = "CHANGE-2026-09-12-040"
POLICY_VERSION = "market-quote-integrity-v2"
ODDS_CONTRACT_CHANGE_ID = "CHANGE-2026-09-21-050"
ODDS_SOURCE_FAMILY = "rapidapi-recent-odds"
ODDS_SOURCE_CONTRACT_VERSION = "rapidapi-recent-gated-v1"
ODDS_IDENTITY_POLICY_VERSION = "rapidapi-event-bilateral-v1"
ODDS_FRESHNESS_SEMANTICS = "observed-at-capture-unverified-age-v1"
ODDS_BOOKMAKER_POLICY = "single-factual-bookmaker-bilateral-v1"

_ODDS_SOURCE_CONTRACT = {
    "source_family": ODDS_SOURCE_FAMILY,
    "source_contract_version": ODDS_SOURCE_CONTRACT_VERSION,
    "market_integrity_policy_version": POLICY_VERSION,
    "identity_policy_version": ODDS_IDENTITY_POLICY_VERSION,
    "freshness_semantics": ODDS_FRESHNESS_SEMANTICS,
    "bookmaker_policy": ODDS_BOOKMAKER_POLICY,
}
ODDS_SOURCE_CONTRACT_FINGERPRINT = hashlib.sha256(
    json.dumps(
        _ODDS_SOURCE_CONTRACT,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()[:20]
CONSENSUS_MAX_DISTANCE = 0.15
# Uma cotação bilateral válida, ligada a um evento pré-live verificado, é
# suficiente para produzir o relatório/pricing. Dois ou mais bookmakers
# continuam a ser necessários apenas para chamar ao resultado "consenso".
# Bloquear todo o relatório por haver apenas um bookmaker descartava mercados
# reais que a própria RapidAPI expõe (ex.: WTA Guadalajara).
MIN_OPERATIONAL_BOOKMAKERS = 1
DEFAULT_EXCLUSIONS_PATH = Path("data/validation/market-integrity-exclusions-v1.json")

MARKET_BOUNDARY_SENTINEL = "MARKET_BOUNDARY_SENTINEL"
MONEYLINE_INCOMPLETE = "MONEYLINE_INCOMPLETE"
MONEYLINE_NON_NUMERIC = "MONEYLINE_NON_NUMERIC"
MONEYLINE_NON_FINITE = "MONEYLINE_NON_FINITE"
MONEYLINE_ODDS_AT_OR_BELOW_ONE = "MONEYLINE_ODDS_AT_OR_BELOW_ONE"
BOOKMAKER_UNAVAILABLE = "BOOKMAKER_UNAVAILABLE"
NO_VALID_MONEYLINE_CANDIDATE = "NO_VALID_MONEYLINE_CANDIDATE"
INSUFFICIENT_BOOKMAKER_CONSENSUS = "INSUFFICIENT_BOOKMAKER_CONSENSUS"
CROSS_BOOK_OUTLIER = "CROSS_BOOK_OUTLIER"
CROSS_BOOK_DISPERSION = "CROSS_BOOK_DISPERSION"


def operational_contract_metadata(captured_at_utc: str | None = None) -> dict[str, Any]:
    """Metadados prospetivos do contrato operacional, sem reclassificar histórico."""
    return {
        "odds_source_contract_version": ODDS_SOURCE_CONTRACT_VERSION,
        "odds_source_contract_fingerprint": ODDS_SOURCE_CONTRACT_FINGERPRINT,
        "odds_source_contract": dict(_ODDS_SOURCE_CONTRACT),
        "odds_contract_activation": {
            "change_id": ODDS_CONTRACT_CHANGE_ID,
            "contract_version": ODDS_SOURCE_CONTRACT_VERSION,
            "boundary": "FIRST_POST_MERGE_OBSERVATION_WITH_CONTRACT_FINGERPRINT",
            "activation_commit": os.environ.get("GITHUB_SHA"),
            "activation_run_id": os.environ.get("GITHUB_RUN_ID"),
            "activation_observed_at_utc": captured_at_utc,
        },
    }


def is_operational_pricing_provenance(provenance: Mapping[str, Any] | None) -> bool:
    """Fonte única de verdade para eligibility: qualquer ausência falha fechada."""
    if not isinstance(provenance, Mapping):
        return False
    integrity = provenance.get("market_integrity")
    if not isinstance(integrity, Mapping):
        return False
    return all((
        provenance.get("operational_pricing_eligible") is True,
        provenance.get("odds_source_contract_version") == ODDS_SOURCE_CONTRACT_VERSION,
        provenance.get("odds_source_contract_fingerprint") == ODDS_SOURCE_CONTRACT_FINGERPRINT,
        bool(provenance.get("event_id")),
        str(provenance.get("identity_mapping_status") or "").upper() == "VERIFIED",
        bool(str(provenance.get("bookmaker") or "").strip()),
        provenance.get("freshness_status") == "OBSERVED_AT_CAPTURE_UNVERIFIED_AGE",
        integrity.get("policy_version") == POLICY_VERSION,
        integrity.get("status") == "AVAILABLE",
    ))


def is_operational_pricing_payload(
    payload: Mapping[str, Any] | None,
    *,
    require_pricing_contract: bool = False,
) -> bool:
    """Defesa downstream simples baseada na decisão canónica da provenance."""
    if not isinstance(payload, Mapping):
        return False
    eligible = all((
        payload.get("odds_operational_pricing_eligible") is True,
        payload.get("odds_source_contract_version") == ODDS_SOURCE_CONTRACT_VERSION,
        payload.get("odds_source_contract_fingerprint") == ODDS_SOURCE_CONTRACT_FINGERPRINT,
    ))
    if not eligible or not require_pricing_contract:
        return eligible
    pricing = payload.get("pricing")
    return bool(
        isinstance(pricing, Mapping)
        and pricing.get("available") is True
        and pricing.get("odds_source_contract_version") == ODDS_SOURCE_CONTRACT_VERSION
        and pricing.get("odds_source_contract_fingerprint") == ODDS_SOURCE_CONTRACT_FINGERPRINT
    )


def validate_moneyline_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Valida um par sem inferir nem corrigir odds recebidas do provider."""
    bookmaker = str(candidate.get("bookmaker") or "").strip()
    result = {
        "bookmaker": bookmaker or None,
        "provider_timestamp": candidate.get("provider_timestamp"),
        "valid": False,
        "reason_code": None,
    }
    if not bookmaker:
        result["reason_code"] = BOOKMAKER_UNAVAILABLE
        return result
    raw_a, raw_b = candidate.get("odd_a"), candidate.get("odd_b")
    if raw_a in (None, "") or raw_b in (None, ""):
        result["reason_code"] = MONEYLINE_INCOMPLETE
        return result
    try:
        odd_a, odd_b = float(raw_a), float(raw_b)
    except (TypeError, ValueError):
        result["reason_code"] = MONEYLINE_NON_NUMERIC
        return result
    if not math.isfinite(odd_a) or not math.isfinite(odd_b):
        result["reason_code"] = MONEYLINE_NON_FINITE
        return result
    result.update({"odd_a": odd_a, "odd_b": odd_b})
    if min(odd_a, odd_b) <= 1.01 and max(odd_a, odd_b) >= 10.0:
        result["reason_code"] = MARKET_BOUNDARY_SENTINEL
        return result
    if odd_a <= 1.0 or odd_b <= 1.0:
        result["reason_code"] = MONEYLINE_ODDS_AT_OR_BELOW_ONE
        return result
    implied_a, implied_b = 1.0 / odd_a, 1.0 / odd_b
    total = implied_a + implied_b
    if not math.isfinite(total) or total <= 0:
        result["reason_code"] = MONEYLINE_NON_FINITE
        return result
    result.update({
        "valid": True,
        "reason_code": None,
        "devig_probability_a": implied_a / total,
        "devig_probability_b": implied_b / total,
        "overround": total - 1.0,
        "integrity_status": "CANDIDATE_VALID",
        "operational_pricing_eligible": False,
    })
    return result


def evaluate_moneyline_market(candidates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aplica validação individual, consenso e seleção operacional fail-closed."""
    checked = [validate_moneyline_candidate(candidate) for candidate in candidates]
    valid = [dict(candidate) for candidate in checked if candidate.get("valid")]
    rejected = [dict(candidate) for candidate in checked if not candidate.get("valid")]

    def unavailable(reason_code: str, *, median_a: float | None = None,
                    dispersion: float | None = None) -> dict[str, Any]:
        return {
            "status": "UNAVAILABLE",
            "policy_version": POLICY_VERSION,
            "reason_code": reason_code,
            "selected": None,
            "valid_candidates": valid,
            "rejected_candidates": rejected,
            "candidate_count": len(checked),
            "valid_candidate_count": len(valid),
            "coherent_bookmaker_count": 0,
            "minimum_operational_bookmakers": MIN_OPERATIONAL_BOOKMAKERS,
            "median_devig_probability_a": median_a,
            "dispersion_pp": round(100.0 * dispersion, 4) if dispersion is not None else None,
        }

    if not valid:
        rejection_codes = {item.get("reason_code") for item in rejected}
        reason = next(iter(rejection_codes)) if len(rejection_codes) == 1 else NO_VALID_MONEYLINE_CANDIDATE
        return unavailable(str(reason or NO_VALID_MONEYLINE_CANDIDATE))

    initial_median = statistics.median(item["devig_probability_a"] for item in valid)
    survivors = valid
    if len(valid) >= 3:
        survivors = []
        for candidate in valid:
            if abs(candidate["devig_probability_a"] - initial_median) > CONSENSUS_MAX_DISTANCE:
                candidate["integrity_status"] = CROSS_BOOK_OUTLIER
                candidate["reason_code"] = CROSS_BOOK_OUTLIER
                rejected.append({
                    "bookmaker": candidate.get("bookmaker"),
                    "odd_a": candidate.get("odd_a"),
                    "odd_b": candidate.get("odd_b"),
                    "reason_code": CROSS_BOOK_OUTLIER,
                })
            else:
                survivors.append(candidate)

    if not survivors:
        return unavailable(NO_VALID_MONEYLINE_CANDIDATE, median_a=initial_median)

    # Não há consenso a medir com uma só casa, mas existe uma Moneyline
    # bilateral estruturalmente válida e observada nesta execução. Mantemos a
    # proveniência explícita para que o relatório não a apresente como média
    # de mercado nem como arbitragem.
    if len(survivors) == 1:
        selected = survivors[0]
        selected["integrity_status"] = "SINGLE_BOOKMAKER_OPERATIONAL"
        selected["reason_code"] = None
        selected["operational_pricing_eligible"] = True
        return {
            "status": "AVAILABLE",
            "policy_version": POLICY_VERSION,
            "reason_code": None,
            "pricing_basis": "single_bookmaker",
            "selected": dict(selected),
            "valid_candidates": valid,
            "rejected_candidates": rejected,
            "candidate_count": len(checked),
            "valid_candidate_count": len(valid),
            "coherent_bookmaker_count": 1,
            "minimum_operational_bookmakers": MIN_OPERATIONAL_BOOKMAKERS,
            "median_devig_probability_a": initial_median,
            "dispersion_pp": None,
        }

    probabilities = [candidate["devig_probability_a"] for candidate in survivors]
    dispersion = max(probabilities) - min(probabilities)
    if dispersion > CONSENSUS_MAX_DISTANCE:
        for candidate in survivors:
            candidate["integrity_status"] = CROSS_BOOK_DISPERSION
            candidate["reason_code"] = CROSS_BOOK_DISPERSION
        return unavailable(
            CROSS_BOOK_DISPERSION,
            median_a=statistics.median(probabilities),
            dispersion=dispersion,
        )

    consensus_median = statistics.median(probabilities)
    for candidate in survivors:
        candidate["integrity_status"] = "COHERENT"
        candidate["reason_code"] = None
        candidate["operational_pricing_eligible"] = True
    selected = min(
        survivors,
        key=lambda item: (
            round(abs(item["devig_probability_a"] - consensus_median), 12),
            item["overround"],
            str(item["bookmaker"]).casefold(),
        ),
    )
    selected["integrity_status"] = "SELECTED_OPERATIONAL"
    return {
        "status": "AVAILABLE",
        "policy_version": POLICY_VERSION,
        "reason_code": None,
        "pricing_basis": "cross_bookmaker_consensus",
        "selected": dict(selected),
        "valid_candidates": valid,
        "rejected_candidates": rejected,
        "candidate_count": len(checked),
        "valid_candidate_count": len(valid),
        "coherent_bookmaker_count": len(survivors),
        "minimum_operational_bookmakers": MIN_OPERATIONAL_BOOKMAKERS,
        "median_devig_probability_a": consensus_median,
        "dispersion_pp": round(100.0 * dispersion, 4),
    }


def read_exclusions(path: Path = DEFAULT_EXCLUSIONS_PATH) -> list[dict[str, Any]]:
    """Lê a quarentena aditiva; nunca altera snapshots, reports ou PAPER."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    records = document.get("exclusions") if isinstance(document, Mapping) else None
    if not isinstance(records, list):
        return []
    return [dict(item) for item in records if isinstance(item, Mapping)]


def excluded_paper_keys(path: Path = DEFAULT_EXCLUSIONS_PATH) -> set[str]:
    return {
        str(item["paper_key"])
        for item in read_exclusions(path)
        if item.get("paper_key")
    }


def excluded_snapshot_keys(path: Path = DEFAULT_EXCLUSIONS_PATH) -> set[str]:
    return {
        str(item["snapshot_key"])
        for item in read_exclusions(path)
        if item.get("snapshot_key")
    }
