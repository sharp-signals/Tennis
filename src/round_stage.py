"""Stable tournament-stage taxonomy for observational performance views.

The provider uses numeric round identifiers consistently across draw sizes:
1-3 are qualifying rounds, 4-7 are main-draw rounds before the quarter-finals,
and 9/10/12 are quarter-final, semi-final and final. Unknown identifiers and
labels stay unresolved; they are never inferred from date or player names.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


QUALIFYING = "QUALIFYING"
EARLY = "EARLY_ROUNDS"
LATE = "LATE_STAGES"
UNRESOLVED = "ROUND_UNRESOLVED"


def _token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", text.encode("ascii", "ignore").decode().lower())


def classify_round_stage(*, round_id: Any = None, round_label: Any = None) -> str:
    """Classify only factual provider round evidence into the project buckets."""
    try:
        numeric = int(str(round_id).strip())
    except (TypeError, ValueError):
        numeric = None
    if numeric in {1, 2, 3}:
        return QUALIFYING
    if numeric in {4, 5, 6, 7}:
        return EARLY
    if numeric in {9, 10, 12}:
        return LATE

    label = _token(round_label)
    if not label:
        return UNRESOLVED
    if label in {
        "q", "qual", "qualifying", "qualification", "qualifier",
        "q1", "q2", "q3", "qualifying1", "qualifying2", "qualifying3",
        "qualification1", "qualification2", "qualification3",
    }:
        return QUALIFYING
    if label in {
        "r128", "roundof128", "1stround", "firstround",
        "r64", "roundof64", "2ndround", "secondround",
        "r32", "roundof32", "3rdround", "thirdround",
        "r16", "roundof16", "4thround", "fourthround",
    }:
        return EARLY
    if label in {
        "qf", "quarterfinal", "quarterfinals",
        "sf", "semifinal", "semifinals", "f", "final",
    }:
        return LATE
    return UNRESOLVED
