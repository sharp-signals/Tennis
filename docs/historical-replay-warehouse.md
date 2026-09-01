# Historical Replay Warehouse

`CHANGE-2026-09-01-021` adds an isolated historical validation path. It does not replace `src/backtest.py`, alter Fenzobot weights, pricing, PAPER, reports, alerts, or operational snapshots.

## Pipeline and storage

`RapidAPI → immutable raw cache → normalized matches/quotes → ex-ante snapshot → current deterministic engine → BACKTEST_RECONSTRUCTED → settlement`

The default SQLite path is `data/historical_warehouse/sharp_history.sqlite3`, configurable through `HISTORICAL_WAREHOUSE_PATH`. Real databases and dumps are ignored by Git. Local runs persist the database. GitHub Actions storage is ephemeral: audit/pilot databases are short-lived artifacts, not durable cloud storage. A persistent cloud backend requires a separate BRAIN decision.

The schema is versioned in `src/historical_warehouse.py` and contains:

- `raw_responses`: immutable successful-response cache keyed by source, endpoint, normalized parameters and source/schema version;
- `matches`: match identity and separately stored `EX_POST_ONLY` outcome;
- `market_quotes`: quote provenance and honest temporal semantics;
- `replay_snapshots`: deterministic ex-ante features, coverage, missingness, versions and hashes;
- `replay_runs` / `replay_outputs`: experiment and `BACKTEST_RECONSTRUCTED` output, never PAPER;
- `backfill_state`: restart/resume state.

## Temporal classes

- `EXACT_EX_ANTE`: timestamp proves availability before the match;
- `RECONSTRUCTED_EX_ANTE`: reconstructed only from observations before the cutoff;
- `EX_POST_ONLY`: result/settlement, isolated from feature generation;
- `UNAVAILABLE`: not sufficiently safe. It is never converted into zero.

H2H, last-ten form and surface record are reconstructed from matches strictly before `as_of_utc`. `src/backtest.py`'s 21-day safety buffer remains mandatory when a source provides only tournament-start precision. Current `singlesRanking` is never used for a historical match. A rank embedded in that historical record is marked reconstructed until the audit proves stronger semantics. Annual/career aggregates are not fed directly into replay because they may include future matches.

Historical `odd1/odd2` is preserved, but without a bookmaker timestamp it is `temporal_role=UNKNOWN` and `temporal_class=UNAVAILABLE`; it is not described as opening, closing, T-24h or T-1h.

Transient errors, 404 responses and empty dynamic histories are not written to the immutable successful-response cache, so a temporary absence cannot block future discovery forever.

## Commands

Capability audit (small documented ATP/WTA sample, JSON + Markdown, no large backfill):

```bash
LLM_MODE=disabled LLM_POLICY=never ALLOW_PAID_LLM=0 \
python -m scripts.historical_capability_audit --max-calls 8
```

Controlled pilot (default player IDs are already documented/observed in this repository):

```bash
LLM_MODE=disabled LLM_POLICY=never ALLOW_PAID_LLM=0 RAPIDAPI_KEY=... \
python -m scripts.historical_replay pilot --tour both --max-matches 100 --max-calls 8
```

Offline replay (no `RAPIDAPI_KEY` required):

```bash
LLM_MODE=disabled LLM_POLICY=never ALLOW_PAID_LLM=0 \
python -m scripts.historical_replay replay --tour both --max-matches 100
```

A larger backfill is deliberately blocked unless `--confirm-backfill I_UNDERSTAND_THE_QUOTA` is supplied. No scheduled workflow exists; `.github/workflows/historical-backfill.yml` is `workflow_dispatch` only.

## Shared quota

Every historical request uses `fetch_data._rapidapi_get(..., rapidapi_purpose="backfill")`, including retries. Cache hits make no request. Operational and historical calls use the same daily usage/inflight accounting and endpoint counters. Defaults:

- global hard guard: 4,500/day;
- operational reserve: 1,500;
- historical global ceiling: 3,000 accumulated calls/day.

If operational work has already used 800 calls, historical acquisition can use at most another 2,200. Historical work stops at global 3,000; operational work may continue under the absolute 4,500 guard.

## Current limitations

- Actual subscription depth must be measured by the capability audit; endpoint names are not proof.
- No separate historical-odds endpoint is currently documented in the repository.
- Quote temporal semantics and bookmaker can be absent.
- Historical rankings may be unavailable.
- The initial player-list acquisition is a controlled capability/pilot, not a complete match-universe crawler.
- A ~100-match pilot measures reconstruction coverage, cache rate and storage only; it must not tune weights or support performance claims.
