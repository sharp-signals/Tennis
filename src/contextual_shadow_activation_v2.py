"""Fail-closed activation boundary for contextual SHADOW v2."""

from __future__ import annotations

import os
from typing import Mapping


ENV_NAME = "CONTEXTUAL_SHADOW_V2_MODE"
ACTIVE_VALUE = "observe"


def activation_state(environment: Mapping[str, str] | None = None) -> dict:
    """Return an auditable state; absence or an unknown value stays disabled."""
    source = os.environ if environment is None else environment
    configured = str(source.get(ENV_NAME, "")).strip().casefold()
    if configured == ACTIVE_VALUE:
        return {
            "active": True,
            "mode": "PROSPECTIVE_SHADOW_ONLY",
            "reason_code": "EXPLICIT_OBSERVE_MODE",
            "environment_name": ENV_NAME,
        }
    return {
        "active": False,
        "mode": "DISABLED",
        "reason_code": (
            "ACTIVATION_NOT_CONFIGURED" if not configured
            else "INVALID_ACTIVATION_VALUE"
        ),
        "environment_name": ENV_NAME,
    }
