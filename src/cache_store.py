"""Cache JSON persistente, versionada e com escrita atómica."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

CACHE_SCHEMA_VERSION = 1
_LOCK = threading.RLock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class JsonCacheStore:
    """Um ficheiro por entidade, com várias entradas e TTL independente."""

    def __init__(
        self,
        base_dir: str | os.PathLike[str] = "data/cache",
        *,
        schema_version: int = CACHE_SCHEMA_VERSION,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.schema_version = int(schema_version)
        self.clock = clock

    def entity_path(self, *parts: object) -> Path:
        clean: list[str] = []
        for part in parts:
            value = str(part).strip()
            if not value or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError(f"Parte de caminho inválida: {part!r}")
            clean.append(value)
        if not clean:
            raise ValueError("Caminho vazio.")
        return self.base_dir.joinpath(*clean)

    def get_entry(
        self,
        path: str | os.PathLike[str],
        entry_name: str,
        *,
        max_age_hours: float,
    ) -> Any | None:
        if max_age_hours < 0:
            raise ValueError("max_age_hours não pode ser negativo.")
        target = Path(path)
        with _LOCK:
            document = self._read(target)
            if document is None:
                return None
            entry = document["entries"].get(entry_name)
            if not isinstance(entry, dict) or "data" not in entry:
                return None
            fetched_at = _from_iso(entry.get("fetched_at"))
            if fetched_at is None:
                return None
            age_hours = (self.clock() - fetched_at).total_seconds() / 3600
            if age_hours < 0 or age_hours >= max_age_hours:
                return None
            return entry["data"]

    def set_entry(
        self,
        path: str | os.PathLike[str],
        entry_name: str,
        data: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(entry_name, str) or not entry_name:
            raise ValueError("entry_name inválido.")
        target = Path(path)
        with _LOCK:
            document = self._read(target, quarantine_corrupt=True)
            now = _to_iso(self.clock())
            if document is None:
                document = {
                    "schema_version": self.schema_version,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": dict(metadata or {}),
                    "entries": {},
                }
            else:
                document["updated_at"] = now
                if metadata:
                    document["metadata"].update(dict(metadata))
            document["entries"][entry_name] = {
                "fetched_at": now,
                "data": data,
            }
            self._atomic_write(target, document)

    def _read(
        self,
        path: Path,
        *,
        quarantine_corrupt: bool = False,
    ) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            if quarantine_corrupt:
                self._quarantine(path)
            return None
        if not isinstance(document, dict):
            return None
        if document.get("schema_version") != self.schema_version:
            return None
        if not isinstance(document.get("entries"), dict):
            return None
        if not isinstance(document.get("metadata"), dict):
            document["metadata"] = {}
        return document

    def _quarantine(self, path: Path) -> None:
        stamp = self.clock().strftime("%Y%m%dT%H%M%SZ")
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
        index = 1
        while candidate.exists():
            candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{index}")
            index += 1
        try:
            os.replace(path, candidate)
        except OSError:
            pass

    @staticmethod
    def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
