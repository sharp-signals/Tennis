"""Coverage audit for the future contextual recent-form family.

CHANGE-2026-11-02-175.  This module is deliberately observational: it does not
change the current engine, reports, pricing or PAPER logic.  It measures which
facts are actually present in a historical frame before a recent-form equation
is designed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from . import valuebetennis_history


CHANGE_ID = "CHANGE-2026-11-02-175"
SCHEMA_VERSION = 1
DEFAULT_WINDOW_DAYS = 90

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_date": ("tourney_date", "date", "Date"),
    "tournament": ("tourney_name", "Tournament", "tournament"),
    "tier": ("tier", "category", "Tier", "tourney_level"),
    "surface": ("surface", "Surface", "Court", "court"),
    "round": ("round", "Round"),
    "best_of": ("best_of", "Best of"),
    "winner_name": ("winner_name", "Winner"),
    "loser_name": ("loser_name", "Loser"),
    "winner_rank": ("winner_rank", "WRank"),
    "loser_rank": ("loser_rank", "LRank"),
    "score": ("score", "Score"),
    "comment": ("Comment", "comment", "status"),
    "scope": ("_history_competition_scope",),
    "indoor": ("indoor",),
    "court": ("Court", "court", "source_surface"),
}

SET_COLUMNS = ("W1", "L1", "W2", "L2", "W3", "L3", "W4", "L4", "W5", "L5")
TERMINAL_NON_STANDARD_TOKENS = ("ret", "w/o", "walkover", "abd", "abandoned", "unfinished")


def _column(frame: pd.DataFrame, logical_name: str) -> pd.Series:
    for candidate in FIELD_ALIASES[logical_name]:
        if candidate in frame.columns:
            return frame[candidate]
    return pd.Series([None] * len(frame), index=frame.index, dtype="object")


def _present(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.notna() & (text != "") & (text.str.casefold() != "nan")


def _positive_number(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.notna() & (numeric > 0)


def _parse_history_dates(series: pd.Series) -> pd.Series:
    raw = series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    unresolved = compact.isna()
    if unresolved.any():
        compact.loc[unresolved] = pd.to_datetime(
            raw.loc[unresolved], errors="coerce", utc=True, dayfirst=False,
        )
    return compact


def _completion_classification_available(frame: pd.DataFrame) -> pd.Series:
    score = _column(frame, "score")
    comment = _column(frame, "comment")
    return _present(score) | _present(comment)


def _is_non_standard_completion(frame: pd.DataFrame) -> pd.Series:
    combined = (
        _column(frame, "score").astype("string").fillna("")
        + " "
        + _column(frame, "comment").astype("string").fillna("")
    ).str.casefold()
    result = pd.Series(False, index=frame.index)
    for token in TERMINAL_NON_STANDARD_TOKENS:
        result |= combined.str.contains(token, regex=False, na=False)
    return result


def _complete_score(frame: pd.DataFrame) -> pd.Series:
    score_present = _present(_column(frame, "score"))
    set_pairs = []
    for winner_col, loser_col in zip(SET_COLUMNS[::2], SET_COLUMNS[1::2]):
        if winner_col in frame.columns and loser_col in frame.columns:
            set_pairs.append(frame[winner_col].notna() & frame[loser_col].notna())
    if set_pairs:
        completed_sets = sum(pair.astype(int) for pair in set_pairs)
        set_score_present = completed_sets >= 2
    else:
        set_score_present = pd.Series(False, index=frame.index)
    return (score_present | set_score_present) & ~_is_non_standard_completion(frame)


def _scope_available(frame: pd.DataFrame, universe: str) -> pd.Series:
    explicit = _present(_column(frame, "scope"))
    # A caller-supplied universe is valid provenance for a frame that was
    # loaded from a circuit-specific source (for example WTA main).
    declared = str(universe or "").strip().casefold() in {"atp", "wta", "challenger"}
    return explicit | declared


def _indoor_outdoor_available(frame: pd.DataFrame) -> pd.Series:
    indoor = _column(frame, "indoor")
    indoor_known = indoor.notna()
    court = _column(frame, "court").astype("string").str.casefold()
    court_known = court.str.contains("indoor|outdoor", regex=True, na=False)
    return indoor_known | court_known


def normalize_recent_match_record(
    row: Mapping[str, Any], *, universe: str,
) -> dict[str, Any]:
    """Return the factual v1 record without deriving a player signal."""

    def first(logical_name: str) -> Any:
        for candidate in FIELD_ALIASES[logical_name]:
            value = row.get(candidate)
            if value is not None and not pd.isna(value) and str(value).strip():
                return value
        return None

    date_value = first("event_date")
    parsed = _parse_history_dates(pd.Series([date_value])).iloc[0]
    scope = first("scope") or str(universe).strip().casefold()
    winner_rank = pd.to_numeric(pd.Series([first("winner_rank")]), errors="coerce").iloc[0]
    loser_rank = pd.to_numeric(pd.Series([first("loser_rank")]), errors="coerce").iloc[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "universe": str(universe).strip().casefold(),
        "event_date": parsed.date().isoformat() if not pd.isna(parsed) else None,
        "tournament": first("tournament"),
        "tier": first("tier"),
        "competition_scope": scope,
        "surface": first("surface"),
        "round": first("round"),
        "best_of": first("best_of"),
        "winner_name": first("winner_name"),
        "loser_name": first("loser_name"),
        "winner_rank": float(winner_rank) if pd.notna(winner_rank) and winner_rank > 0 else None,
        "loser_rank": float(loser_rank) if pd.notna(loser_rank) and loser_rank > 0 else None,
        "score": first("score"),
        "completion_comment": first("comment"),
        "source_file": row.get("_history_source_file") or row.get("source"),
    }


def audit_recent_form_coverage(
    frame: pd.DataFrame,
    *,
    universe: str,
    as_of: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Measure factual coverage in the safe, completed-day lookback window.

    Sources with day-only precision cannot prove whether a match on the cutoff
    date finished before a target fixture.  The audit therefore excludes the
    whole cutoff date.  A future replay with exact timestamps can use a tighter
    boundary without changing this coverage contract.
    """
    if int(window_days) <= 0:
        raise ValueError("window_days tem de ser positivo")
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    as_of = as_of.astimezone(timezone.utc)
    cutoff_date = as_of.date()
    start_date = cutoff_date - timedelta(days=int(window_days))

    dates = _parse_history_dates(_column(frame, "event_date"))
    valid_date = dates.notna()
    event_dates = dates.dt.date
    safe = valid_date & (event_dates >= start_date) & (event_dates < cutoff_date)
    future_or_cutoff = valid_date & (event_dates >= cutoff_date)
    window = frame.loc[safe].copy()

    if window.empty:
        return {
            "schema_version": SCHEMA_VERSION,
            "change_id": CHANGE_ID,
            "universe": universe,
            "source": source_label,
            "as_of_utc": as_of.isoformat(),
            "window_days": int(window_days),
            "window_start": start_date.isoformat(),
            "safe_cutoff_exclusive": cutoff_date.isoformat(),
            "rows_source": int(len(frame)),
            "rows_window": 0,
            "rows_unresolved_date": int((~valid_date).sum()),
            "rows_cutoff_or_future_excluded": int(future_or_cutoff.sum()),
            "coverage": {},
            "quality_readiness": {
                "core_result_and_ranking": {"count": 0, "pct": None},
                "full_context": {"count": 0, "pct": None},
            },
        }

    total = len(window)
    masks = {
        "result_identity": _present(_column(window, "winner_name")) & _present(_column(window, "loser_name")),
        "historical_ranking_bilateral": _positive_number(_column(window, "winner_rank"))
        & _positive_number(_column(window, "loser_rank")),
        "surface": _present(_column(window, "surface")),
        "score_complete": _complete_score(window),
        "competition_scope": _scope_available(window, universe),
        "tournament_tier": _present(_column(window, "tier")),
        "round": _present(_column(window, "round")),
        "best_of": _positive_number(_column(window, "best_of")),
        "indoor_outdoor": _indoor_outdoor_available(window),
        "completion_classification": _completion_classification_available(window),
    }
    coverage = {
        key: {"count": int(mask.sum()), "pct": round(100.0 * float(mask.sum()) / total, 1)}
        for key, mask in masks.items()
    }
    core = masks["result_identity"] & masks["historical_ranking_bilateral"]
    full = (
        core
        & masks["surface"]
        & masks["competition_scope"]
        & masks["tournament_tier"]
        & masks["round"]
        & masks["score_complete"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "universe": universe,
        "source": source_label,
        "as_of_utc": as_of.isoformat(),
        "window_days": int(window_days),
        "window_start": start_date.isoformat(),
        "safe_cutoff_exclusive": cutoff_date.isoformat(),
        "rows_source": int(len(frame)),
        "rows_window": int(total),
        "rows_unresolved_date": int((~valid_date).sum()),
        "rows_cutoff_or_future_excluded": int(future_or_cutoff.sum()),
        "coverage": coverage,
        "quality_readiness": {
            "core_result_and_ranking": {
                "count": int(core.sum()), "pct": round(100.0 * float(core.sum()) / total, 1),
            },
            "full_context": {
                "count": int(full.sum()), "pct": round(100.0 * float(full.sum()) / total, 1),
            },
        },
    }


def load_local_audit_universes(cache_dir: Path) -> dict[str, tuple[pd.DataFrame, str]]:
    """Load repository caches without network calls or provider credits."""
    cache_dir = Path(cache_dir)
    atp = valuebetennis_history.load_history(cache_dir, refresh_current=False)
    scope = atp.get("_history_competition_scope")
    if scope is None:
        atp_main = atp.copy()
        challenger = atp.iloc[0:0].copy()
    else:
        atp_main = atp[scope == "main"].copy()
        challenger = atp[scope == "challenger"].copy()

    wta_frames = []
    for path in sorted(cache_dir.glob("wta_tdcouk_*.csv")):
        frame = pd.read_csv(path)
        frame = frame.rename(columns={
            "Winner": "winner_name", "Loser": "loser_name",
            "Surface": "surface", "WRank": "winner_rank",
            "LRank": "loser_rank", "Best of": "best_of", "Round": "round",
        })
        if "Date" in frame.columns:
            frame["tourney_date"] = pd.to_datetime(
                frame["Date"], errors="coerce",
            ).dt.strftime("%Y%m%d")
        frame["_history_source_file"] = path.name
        frame["_history_competition_scope"] = "main"
        wta_frames.append(frame)
    wta = pd.concat(wta_frames, ignore_index=True, sort=False) if wta_frames else pd.DataFrame()

    return {
        "atp": (atp_main, "valuebetennis_local_cache"),
        "wta": (wta, "tennisdata_wta_local_cache"),
        "challenger": (challenger, "valuebetennis_local_cache"),
    }


def audit_local_caches(
    cache_dir: Path,
    *,
    as_of: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    universes: Iterable[str] = ("atp", "wta", "challenger"),
) -> dict[str, Any]:
    loaded = load_local_audit_universes(cache_dir)
    reports = {}
    for universe in universes:
        frame, source = loaded[universe]
        reports[universe] = audit_recent_form_coverage(
            frame,
            universe=universe,
            as_of=as_of,
            window_days=window_days,
            source_label=source,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "mode": "LOCAL_CACHE_READ_ONLY",
        "reports": reports,
    }


def audit_operational_histories(
    *,
    as_of: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Audit the same history loader used by reports.

    This may access the public historical provider selected by ``get_history``.
    It never calls RapidAPI and never writes operational state.
    """
    from . import fetch_data  # local import keeps cache-only audit lightweight

    atp_all = fetch_data.get_history("atp")
    wta_all = fetch_data.get_history("wta")
    challenger_all = fetch_data.get_history("atp", tier="Challenger 125")

    def select_scope(frame: pd.DataFrame, wanted: str) -> pd.DataFrame:
        scope = frame.get("_history_competition_scope")
        if scope is None:
            return frame.copy() if wanted == "main" else frame.iloc[0:0].copy()
        return frame[scope == wanted].copy()

    sources = {
        "atp": (select_scope(atp_all, "main"), atp_all.attrs.get("history_scope")),
        "wta": (select_scope(wta_all, "main"), wta_all.attrs.get("history_scope")),
        "challenger": (
            select_scope(challenger_all, "challenger"),
            challenger_all.attrs.get("history_scope"),
        ),
    }
    reports = {
        universe: audit_recent_form_coverage(
            frame,
            universe=universe,
            as_of=as_of,
            window_days=window_days,
            source_label=str(source or "operational_get_history"),
        )
        for universe, (frame, source) in sources.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "mode": "OPERATIONAL_HISTORY_READ_ONLY",
        "reports": reports,
    }
