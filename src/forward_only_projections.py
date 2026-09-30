"""Baseline-plus-prospective composition for CHANGE-2026-09-30-067.

The historical document remains the exact Git blob ratified at T0.  New
records are exposed in a separate prospective component; non-additive rates
are never added to the legacy values.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from . import forward_only


CONTINUITY_FIELD = "forward_only_continuity"


class ProjectionContinuityError(RuntimeError):
    pass


def repository_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise ProjectionContinuityError("FORWARD_ONLY_REPOSITORY_ROOT_UNAVAILABLE")


def reference_for(boundary: forward_only.Boundary, relative_path: str) -> Mapping[str, Any]:
    protected = (boundary.manifest or {}).get("protected") or {}
    references = protected.get("historic_aggregate_references") or []
    for reference in references:
        if isinstance(reference, Mapping) and reference.get("path") == relative_path:
            return reference
    raise ProjectionContinuityError(f"PROJECTION_REFERENCE_MISSING:{relative_path}")


def baseline_bytes(
    boundary: forward_only.Boundary,
    relative_path: str,
    *,
    root: Path | None = None,
) -> bytes:
    if not boundary.active:
        raise ProjectionContinuityError("FORWARD_ONLY_NOT_ACTIVE")
    reference = reference_for(boundary, relative_path)
    commit = str((boundary.manifest or {}).get("data_base_commit") or "")
    if not commit:
        raise ProjectionContinuityError("ACTIVATION_DATA_COMMIT_MISSING")
    repo = repository_root(root)
    try:
        value = subprocess.check_output(
            ["git", "show", f"{commit}:{relative_path}"], cwd=repo,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise ProjectionContinuityError(
            f"PROJECTION_BASELINE_GIT_BLOB_UNAVAILABLE:{relative_path}"
        ) from exc
    digest = hashlib.sha256(value).hexdigest()
    if digest != reference.get("sha256_at_t0"):
        raise ProjectionContinuityError(f"PROJECTION_BASELINE_HASH_MISMATCH:{relative_path}")
    return value


def baseline_json(
    boundary: forward_only.Boundary,
    relative_path: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(baseline_bytes(boundary, relative_path, root=root))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionContinuityError(
            f"PROJECTION_BASELINE_JSON_INVALID:{relative_path}"
        ) from exc
    if not isinstance(value, Mapping):
        raise ProjectionContinuityError(f"PROJECTION_BASELINE_JSON_INVALID:{relative_path}")
    return copy.deepcopy(dict(value))


def compose_json(
    *,
    boundary: forward_only.Boundary,
    relative_path: str,
    prospective: Mapping[str, Any],
    root: Path | None = None,
    operational_current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = baseline_json(boundary, relative_path, root=root)
    reference = reference_for(boundary, relative_path)
    baseline[CONTINUITY_FIELD] = {
        "schema_version": 1,
        "change_id": forward_only.CHANGE_ID,
        "status": "ACTIVE",
        "effective_from_utc": (boundary.manifest or {}).get("effective_from_utc"),
        "historical_baseline": {
            "path": relative_path,
            "sha256_at_t0": reference.get("sha256_at_t0"),
            "data_base_commit": (boundary.manifest or {}).get("data_base_commit"),
            "semantics": "PRESERVED_EXACTLY_NOT_RECALCULATED",
        },
        "prospective": copy.deepcopy(dict(prospective)),
        "operational_current": copy.deepcopy(dict(operational_current or {})),
        "combination_semantics": (
            "Historical non-additive metrics remain separate. Prospective counts and "
            "rates describe only post-T0 eligible records and are never summed into legacy rates."
        ),
    }
    return baseline


def historic_component(document: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(document))
    value.pop(CONTINUITY_FIELD, None)
    return value


def validate_historic_component(
    document: Mapping[str, Any], baseline: Mapping[str, Any], *, relative_path: str,
) -> None:
    if historic_component(document) != dict(baseline):
        raise ProjectionContinuityError(
            f"PROTECTED_PROJECTION_HISTORIC_COMPONENT_MUTATED:{relative_path}"
        )


def prospective_document(document: Mapping[str, Any]) -> dict[str, Any]:
    continuity = document.get(CONTINUITY_FIELD)
    if not isinstance(continuity, Mapping):
        return {}
    value = continuity.get("prospective")
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
