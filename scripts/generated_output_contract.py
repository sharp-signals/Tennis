"""Explicit allowlists for generated-data writers (never code or secrets)."""

from __future__ import annotations

from pathlib import PurePosixPath


COMMON = (
    "data/rapidapi_usage_log.json",
    "data/rapidapi_usage_inflight.json",
    "data/run_metrics_log.json",
    "data/maintenance/",
)

PROFILES: dict[str, tuple[str, ...]] = {
    "bot": COMMON + (
        "docs/.nojekyll", "docs/index.html", "docs/relatorios/", "docs/dashboard/",
        "docs/assets/players/",
        "data/analysis_cache/", "data/cache/", "data/fixtures_cache.json",
        "data/tournament_cache.json", "data/calibration_snapshots.json",
        "data/paper_trades.json", "data/market_ledger/", "data/match_identity/",
        "data/validation/", "data/dashboard/", "data/player_images.json",
        "data/player_images_review.json", "data/governance/", "knowledge/players/",
    ),
    "odds-source": COMMON + (
        "data/odds_monitor/", "data/market_ledger/", "data/cache/",
    ),
    "odds-derived": COMMON + (
        "data/dashboard/", "docs/dashboard/", "data/validation/",
        "data/market_ledger/derived/",
    ),
    "odds": COMMON + (
        "data/odds_monitor/", "data/market_ledger/", "data/dashboard/",
        "docs/dashboard/", "data/validation/", "data/cache/",
    ),
    "observability": COMMON + (
        "data/dashboard/", "docs/dashboard/", "data/validation/",
        "data/market_ledger/derived/",
    ),
    "retry": COMMON + (
        "data/market_ledger/", "data/match_identity/", "data/pending_market/",
        "data/cache/",
    ),
    "warmup": COMMON + ("data/cache/", "knowledge/players/"),
    "backtest": COMMON + ("data/backtest_results/",),
    "images": COMMON + (
        "docs/assets/players/", "data/player_images.json", "data/player_images_review.json",
    ),
}


def normalize(path: str) -> str:
    value = PurePosixPath(path.replace("\\", "/")).as_posix().lstrip("./")
    if value == ".." or value.startswith("../"):
        raise ValueError("path escapes repository")
    return value


def is_allowed(path: str, profile: str) -> bool:
    value = normalize(path)
    try:
        rules = PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown generated-output profile: {profile}") from exc
    return any(
        value.startswith(rule) if rule.endswith("/") else value == rule
        for rule in rules
    )
