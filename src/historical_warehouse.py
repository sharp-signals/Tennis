"""SQLite warehouse for temporally safe historical acquisition and replay.

CHANGE-2026-09-01-021/022/023.  The database is deliberately local and disposable
from Git's point of view; provenance and schema live in code, while real
historical payloads remain outside version control.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


SCHEMA_VERSION = 2
CHANGE_ID = "CHANGE-2026-09-02-023"
DEFAULT_PATH = Path(
    os.environ.get(
        "HISTORICAL_WAREHOUSE_PATH",
        "data/historical_warehouse/sharp_history.sqlite3",
    )
)
TEMPORAL_CLASSES = {
    "EXACT_EX_ANTE",
    "RECONSTRUCTED_EX_ANTE",
    "EX_POST_ONLY",
    "UNAVAILABLE",
}


class CorruptCachedPayload(RuntimeError):
    """A cached payload no longer matches its immutable content hash."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalized_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    normalized: dict[str, Any] = {}
    for original_key, value in sorted(params.items(), key=lambda item: str(item[0])):
        key = str(original_key)
        if isinstance(value, (list, tuple, set)):
            normalized[key] = sorted(value) if isinstance(value, set) else list(value)
        elif isinstance(value, Mapping):
            normalized[key] = normalized_params(value)
        else:
            normalized[key] = value
    return normalized


def make_cache_key(
    source: str,
    endpoint: str,
    params: Mapping[str, Any] | None,
    *,
    source_version: str,
    schema_version: int = SCHEMA_VERSION,
) -> str:
    material = {
        "source": source,
        "endpoint": endpoint,
        "params": normalized_params(params),
        "source_version": source_version,
        "schema_version": schema_version,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS warehouse_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_responses (
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    normalized_params TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    provider_timestamp TEXT,
    status INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    source_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    canonical_match_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    endpoint TEXT,
    provider_match_id TEXT,
    provider_timestamp TEXT,
    fetched_at_utc TEXT NOT NULL,
    source_version TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    raw_cache_key TEXT,
    tour TEXT,
    tournament TEXT,
    tournament_id TEXT,
    tournament_level TEXT,
    surface TEXT,
    event_start_utc TEXT NOT NULL,
    date_precision TEXT NOT NULL DEFAULT 'event_exact',
    player_a_id TEXT,
    player_a_name TEXT NOT NULL,
    player_b_id TEXT,
    player_b_name TEXT NOT NULL,
    player_a_rank REAL,
    player_b_rank REAL,
    round TEXT,
    best_of INTEGER,
    identity_temporal_class TEXT NOT NULL,
    ranking_temporal_class TEXT NOT NULL,
    outcome_winner_id TEXT,
    outcome_result TEXT,
    outcome_temporal_class TEXT NOT NULL DEFAULT 'EX_POST_ONLY',
    FOREIGN KEY(raw_cache_key) REFERENCES raw_responses(cache_key)
);

CREATE INDEX IF NOT EXISTS idx_matches_start ON matches(event_start_utc);
CREATE INDEX IF NOT EXISTS idx_matches_players_a ON matches(player_a_id, event_start_utc);
CREATE INDEX IF NOT EXISTS idx_matches_players_b ON matches(player_b_id, event_start_utc);

CREATE TABLE IF NOT EXISTS match_enrichments (
    enrichment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    source_date TEXT,
    temporal_class TEXT NOT NULL,
    match_method TEXT NOT NULL,
    match_confidence TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    conflict INTEGER NOT NULL DEFAULT 0 CHECK(conflict IN (0, 1)),
    UNIQUE(match_id, field_name, source, source_record_key),
    FOREIGN KEY(match_id) REFERENCES matches(canonical_match_id)
);

CREATE INDEX IF NOT EXISTS idx_match_enrichments_match_field
ON match_enrichments(match_id, field_name);

CREATE TABLE IF NOT EXISTS market_quotes (
    quote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    bookmaker TEXT,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odd REAL NOT NULL,
    provider_timestamp TEXT,
    temporal_role TEXT NOT NULL,
    temporal_class TEXT NOT NULL,
    source TEXT NOT NULL,
    endpoint TEXT,
    fetched_at_utc TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    UNIQUE(match_id, bookmaker, market, selection, odd, provider_timestamp, source),
    FOREIGN KEY(match_id) REFERENCES matches(canonical_match_id)
);

CREATE TABLE IF NOT EXISTS replay_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    raw_source_references TEXT NOT NULL,
    feature_values TEXT NOT NULL,
    coverage TEXT NOT NULL,
    missing_data TEXT NOT NULL,
    temporal_rejections TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    pricing_model_version TEXT,
    git_commit TEXT,
    change_id TEXT NOT NULL,
    replay_version TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(match_id, as_of_utc, engine_version, config_hash, replay_version),
    FOREIGN KEY(match_id) REFERENCES matches(canonical_match_id)
);

CREATE TABLE IF NOT EXISTS replay_runs (
    replay_run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    sample_universe TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    git_commit TEXT,
    change_id TEXT NOT NULL,
    metrics_json TEXT,
    results_reference TEXT
);

CREATE TABLE IF NOT EXISTS replay_outputs (
    replay_run_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    universe TEXT NOT NULL CHECK(universe = 'BACKTEST_RECONSTRUCTED'),
    prediction_json TEXT NOT NULL,
    settlement_json TEXT,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY(replay_run_id, match_id),
    FOREIGN KEY(replay_run_id) REFERENCES replay_runs(replay_run_id),
    FOREIGN KEY(snapshot_id) REFERENCES replay_snapshots(snapshot_id),
    FOREIGN KEY(match_id) REFERENCES matches(canonical_match_id)
);

CREATE TABLE IF NOT EXISTS backfill_state (
    item_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    cursor TEXT,
    updated_at_utc TEXT NOT NULL,
    error TEXT
);
"""


class HistoricalWarehouse:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            # Execute every additive DDL statement in one explicit transaction.
            # This upgrades v1 warehouses in place and leaves them untouched if
            # any v2 statement fails.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA_SQL.split(";"):
                statement = statement.strip()
                if statement and not statement.upper().startswith("PRAGMA"):
                    connection.execute(statement)
            version = connection.execute(
                "SELECT value FROM warehouse_meta WHERE key='schema_version'"
            ).fetchone()
            existing_version = int(version["value"]) if version is not None else 0
            if existing_version not in {0, 1, SCHEMA_VERSION}:
                raise RuntimeError(
                    f"Warehouse schema {version['value']} incompatível com {SCHEMA_VERSION}."
                )
            connection.execute(
                "INSERT OR REPLACE INTO warehouse_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO warehouse_meta(key, value) VALUES('change_id', ?)",
                (CHANGE_ID,),
            )

    def get_raw_response(self, cache_key: str) -> Any | None:
        entry = self.get_raw_response_entry(cache_key)
        return entry["payload"] if entry else None

    def get_raw_response_entry(self, cache_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT payload_json, payload_hash, status, fetched_at_utc,
                          provider_timestamp, endpoint, normalized_params
                   FROM raw_responses WHERE cache_key=?""",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise CorruptCachedPayload(f"JSON inválido na cache {cache_key}") from exc
        if payload_hash(payload) != row["payload_hash"]:
            raise CorruptCachedPayload(f"Hash inválido na cache {cache_key}")
        return {
            "payload": payload,
            "status": int(row["status"]),
            "fetched_at_utc": row["fetched_at_utc"],
            "provider_timestamp": row["provider_timestamp"],
            "endpoint": row["endpoint"],
            "normalized_params": json.loads(row["normalized_params"]),
        }

    def put_raw_response(
        self,
        *,
        cache_key: str,
        source: str,
        endpoint: str,
        params: Mapping[str, Any] | None,
        status: int,
        payload: Any,
        source_version: str,
        fetched_at_utc: str | None = None,
        provider_timestamp: str | None = None,
    ) -> None:
        if not 200 <= int(status) < 300:
            raise ValueError("Só respostas externas bem-sucedidas podem entrar na cache imutável.")
        encoded = canonical_json(payload)
        digest = payload_hash(payload)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO raw_responses(
                    cache_key, source, endpoint, normalized_params, fetched_at_utc,
                    provider_timestamp, status, payload_json, payload_hash, source_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cache_key,
                    source,
                    endpoint,
                    canonical_json(normalized_params(params)),
                    fetched_at_utc or utc_now(),
                    provider_timestamp,
                    int(status),
                    encoded,
                    digest,
                    source_version,
                ),
            )

    def upsert_match(self, match: Mapping[str, Any]) -> None:
        for key in ("identity_temporal_class", "ranking_temporal_class", "outcome_temporal_class"):
            if match.get(key) not in TEMPORAL_CLASSES:
                raise ValueError(f"Classe temporal inválida em {key}: {match.get(key)!r}")
        columns = (
            "canonical_match_id", "source", "endpoint", "provider_match_id",
            "provider_timestamp", "fetched_at_utc", "source_version", "payload_hash",
            "raw_cache_key", "tour", "tournament", "tournament_id",
            "tournament_level", "surface", "event_start_utc", "date_precision",
            "player_a_id", "player_a_name", "player_b_id", "player_b_name",
            "player_a_rank", "player_b_rank", "round", "best_of",
            "identity_temporal_class", "ranking_temporal_class", "outcome_winner_id",
            "outcome_result", "outcome_temporal_class",
        )
        values = [match.get(column) for column in columns]
        assignments = ", ".join(
            f"{column}=COALESCE(excluded.{column}, matches.{column})"
            for column in columns[1:]
        )
        with self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO matches({','.join(columns)}) VALUES({','.join('?' for _ in columns)})
                ON CONFLICT(canonical_match_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def add_market_quote(self, quote: Mapping[str, Any]) -> None:
        temporal_class = quote.get("temporal_class")
        if temporal_class not in TEMPORAL_CLASSES:
            raise ValueError(f"Classe temporal inválida: {temporal_class!r}")
        columns = (
            "match_id", "bookmaker", "market", "selection", "odd",
            "provider_timestamp", "temporal_role", "temporal_class", "source",
            "endpoint", "fetched_at_utc", "payload_hash",
        )
        with self.connect() as connection:
            existing = connection.execute(
                """SELECT quote_id FROM market_quotes
                   WHERE match_id=? AND bookmaker IS ? AND market=? AND selection=?
                     AND odd=? AND provider_timestamp IS ? AND source=?""",
                (
                    quote.get("match_id"), quote.get("bookmaker"), quote.get("market"),
                    quote.get("selection"), quote.get("odd"),
                    quote.get("provider_timestamp"), quote.get("source"),
                ),
            ).fetchone()
            if existing is not None:
                return
            connection.execute(
                f"INSERT OR IGNORE INTO market_quotes({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                [quote.get(column) for column in columns],
            )

    def get_match(self, match_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM matches WHERE canonical_match_id=?", (str(match_id),)
            ).fetchone()
        return dict(row) if row else None

    _ENRICHABLE_FIELDS = {
        "player_a_rank", "player_b_rank", "surface", "tournament",
        "tournament_level",
    }

    def add_match_enrichment(self, enrichment: Mapping[str, Any]) -> bool:
        """Append a sourced fact without mutating the provider's match row."""
        field_name = str(enrichment.get("field_name") or "")
        if field_name not in self._ENRICHABLE_FIELDS:
            raise ValueError(f"Campo de enriquecimento inválido: {field_name!r}")
        temporal_class = enrichment.get("temporal_class")
        if temporal_class not in TEMPORAL_CLASSES:
            raise ValueError(f"Classe temporal inválida: {temporal_class!r}")
        match_id = str(enrichment["match_id"])
        target = self.get_match(match_id)
        if target is None:
            raise KeyError(f"Jogo inexistente para enriquecimento: {match_id}")
        value = enrichment.get("value")
        encoded = canonical_json(value)
        conflict = int(target.get(field_name) is not None and canonical_json(target[field_name]) != encoded)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT value_json FROM match_enrichments WHERE match_id=? AND field_name=?",
                (match_id, field_name),
            ).fetchall()
            conflict = int(conflict or any(row["value_json"] != encoded for row in existing))
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO match_enrichments(
                    match_id,field_name,value_json,source,source_record_key,
                    source_date,temporal_class,match_method,match_confidence,
                    payload_hash,fetched_at_utc,conflict
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    match_id, field_name, encoded, enrichment["source"],
                    str(enrichment["source_record_key"]), enrichment.get("source_date"),
                    temporal_class, enrichment["match_method"],
                    enrichment.get("match_confidence") or "deterministic",
                    enrichment.get("payload_hash") or payload_hash(value),
                    enrichment.get("fetched_at_utc") or utc_now(), conflict,
                ),
            )
            return cursor.rowcount == 1

    def list_match_enrichments(self, match_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM match_enrichments WHERE match_id=? ORDER BY enrichment_id",
                (str(match_id),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["value"] = json.loads(item.pop("value_json"))
            item["conflict"] = bool(item["conflict"])
            result.append(item)
        return result

    def get_effective_match(self, match_id: str) -> dict[str, Any] | None:
        """Return original values first, then one unambiguous safe enrichment."""
        match = self.get_match(match_id)
        if match is None:
            return None
        return self._apply_enrichments(match, self.list_match_enrichments(match_id))

    @staticmethod
    def _apply_enrichments(
        match: dict[str, Any], enrichments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        provenance: dict[str, Any] = {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in enrichments:
            grouped.setdefault(item["field_name"], []).append(item)
        for field_name, candidates in grouped.items():
            if match.get(field_name) is not None:
                provenance[field_name] = {"source": "matches", "precedence": "original"}
                continue
            safe = [
                item for item in candidates
                if item["temporal_class"] in {"EXACT_EX_ANTE", "RECONSTRUCTED_EX_ANTE"}
                and not item["conflict"]
            ]
            distinct = {canonical_json(item["value"]) for item in safe}
            if len(distinct) == 1 and safe:
                match[field_name] = safe[0]["value"]
                provenance[field_name] = {
                    "source": safe[0]["source"],
                    "temporal_class": safe[0]["temporal_class"],
                    "match_method": safe[0]["match_method"],
                    "source_record_key": safe[0]["source_record_key"],
                }
        match["enrichment_provenance"] = provenance
        if match.get("player_a_rank") is not None or match.get("player_b_rank") is not None:
            match["ranking_temporal_class"] = "RECONSTRUCTED_EX_ANTE"
        return match

    def list_matches(self, *, tour: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM matches"
        values: list[Any] = []
        if tour:
            query += " WHERE lower(tour)=?"
            values.append(tour.lower())
        query += " ORDER BY event_start_utc"
        if limit is not None:
            query += " LIMIT ?"
            values.append(int(limit))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, values).fetchall()]

    def matches_before(self, as_of_utc: str, *, enriched: bool = False) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM matches WHERE event_start_utc < ? ORDER BY event_start_utc",
                (as_of_utc,),
            ).fetchall()
            enrichment_rows = []
            if enriched:
                enrichment_rows = connection.execute(
                    """SELECT e.* FROM match_enrichments e
                       JOIN matches m ON m.canonical_match_id=e.match_id
                       WHERE m.event_start_utc < ? ORDER BY e.enrichment_id""",
                    (as_of_utc,),
                ).fetchall()
        result = [dict(row) for row in rows]
        if enriched:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in enrichment_rows:
                item = dict(row)
                item["value"] = json.loads(item.pop("value_json"))
                item["conflict"] = bool(item["conflict"])
                grouped.setdefault(item["match_id"], []).append(item)
            return [
                self._apply_enrichments(row, grouped.get(row["canonical_match_id"], []))
                for row in result
            ]
        return result

    def player_matches_before(self, player_id: str, as_of_utc: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM matches
                   WHERE event_start_utc < ? AND (player_a_id=? OR player_b_id=?)
                   ORDER BY event_start_utc DESC""",
                (as_of_utc, str(player_id), str(player_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def store_snapshot(self, snapshot: Mapping[str, Any]) -> bool:
        columns = (
            "snapshot_id", "match_id", "as_of_utc", "raw_source_references",
            "feature_values", "coverage", "missing_data", "temporal_rejections",
            "engine_version", "config_hash", "pricing_model_version", "git_commit",
            "change_id", "replay_version", "snapshot_hash", "created_at_utc",
        )
        values = []
        json_columns = {
            "raw_source_references", "feature_values", "coverage", "missing_data",
            "temporal_rejections",
        }
        for column in columns:
            value = snapshot.get(column)
            values.append(canonical_json(value) if column in json_columns else value)
        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT OR IGNORE INTO replay_snapshots({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                values,
            )
            return cursor.rowcount == 1

    def create_run(self, run: Mapping[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO replay_runs(
                    replay_run_id, mode, engine_version, config_hash, sample_universe,
                    created_at_utc, git_commit, change_id
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    run["replay_run_id"], run["mode"], run["engine_version"],
                    run["config_hash"], canonical_json(run.get("sample_universe") or {}),
                    run.get("created_at_utc") or utc_now(), run.get("git_commit"),
                    run.get("change_id") or CHANGE_ID,
                ),
            )

    def complete_run(self, run_id: str, metrics: Mapping[str, Any], results_reference: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE replay_runs SET completed_at_utc=?, metrics_json=?, results_reference=?
                   WHERE replay_run_id=?""",
                (utc_now(), canonical_json(metrics), results_reference, run_id),
            )

    def store_replay_output(
        self,
        *,
        run_id: str,
        match_id: str,
        snapshot_id: str,
        prediction: Mapping[str, Any],
        settlement: Mapping[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO replay_outputs(
                    replay_run_id, match_id, snapshot_id, universe, prediction_json,
                    settlement_json, created_at_utc
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    run_id, match_id, snapshot_id, "BACKTEST_RECONSTRUCTED",
                    canonical_json(prediction),
                    canonical_json(settlement) if settlement is not None else None,
                    utc_now(),
                ),
            )

    def get_backfill_state(self, item_key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM backfill_state WHERE item_key=?", (item_key,)
            ).fetchone()
        return dict(row) if row else None

    def set_backfill_state(
        self,
        item_key: str,
        status: str,
        *,
        cursor: str | None = None,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        previous = self.get_backfill_state(item_key)
        attempts = int((previous or {}).get("attempts") or 0) + int(increment_attempt)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO backfill_state(item_key,status,attempts,cursor,updated_at_utc,error)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(item_key) DO UPDATE SET status=excluded.status,
                    attempts=excluded.attempts, cursor=excluded.cursor,
                    updated_at_utc=excluded.updated_at_utc, error=excluded.error
                """,
                (item_key, status, attempts, cursor, utc_now(), error),
            )

    def table_count(self, table: str) -> int:
        allowed = {
            "raw_responses", "matches", "market_quotes", "replay_snapshots",
            "replay_runs", "replay_outputs", "backfill_state", "match_enrichments",
        }
        if table not in allowed:
            raise ValueError(f"Tabela inválida: {table}")
        with self.connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def raw_references(self, match_ids: Iterable[str]) -> list[str]:
        ids = [str(item) for item in match_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT raw_cache_key FROM matches WHERE canonical_match_id IN ({placeholders})",
                ids,
            ).fetchall()
        return sorted(row[0] for row in rows if row[0])

    def usable_market_quote_count(self, match_id: str) -> int:
        with self.connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM market_quotes WHERE match_id=? AND temporal_class='EXACT_EX_ANTE'",
                (str(match_id),),
            ).fetchone()[0])
