"""Helpers for reproducible JSON model contracts."""

from __future__ import annotations

import math
from typing import Any


def stabilize_floats(value: Any, *, significant_digits: int = 14) -> Any:
    """Round finite floats so equivalent model fits serialize identically."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return value
        return float(format(value, f".{significant_digits}g"))
    if isinstance(value, dict):
        return {
            key: stabilize_floats(item, significant_digits=significant_digits)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            stabilize_floats(item, significant_digits=significant_digits)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            stabilize_floats(item, significant_digits=significant_digits)
            for item in value
        )
    return value
