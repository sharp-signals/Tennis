"""Testes offline do gestor de cache JSON."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.cache_store import JsonCacheStore


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


class JsonCacheStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.store = JsonCacheStore(self.tmp.name, clock=self.clock)
        self.path = self.store.entity_path("players", "atp", "123.json")

    def test_fresh_entry_round_trip(self) -> None:
        self.store.set_entry(
            self.path,
            "career_stats",
            {"matches": 42},
            metadata={"tour": "atp", "player_id": 123},
        )
        self.assertEqual(
            {"matches": 42},
            self.store.get_entry(
                self.path,
                "career_stats",
                max_age_hours=168,
            ),
        )

    def test_independent_ttl_and_preservation(self) -> None:
        self.store.set_entry(self.path, "career_stats", {"slow": True})
        self.clock.value += timedelta(hours=12)
        self.store.set_entry(self.path, "recent_matches", [{"id": 1}])
        self.clock.value += timedelta(hours=13)
        self.assertIsNone(
            self.store.get_entry(
                self.path,
                "career_stats",
                max_age_hours=24,
            )
        )
        self.assertEqual(
            [{"id": 1}],
            self.store.get_entry(
                self.path,
                "recent_matches",
                max_age_hours=24,
            ),
        )

    def test_schema_mismatch_is_miss(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"schema_version": 99, "entries": {}, "metadata": {}}),
            encoding="utf-8",
        )
        self.assertIsNone(
            self.store.get_entry(self.path, "x", max_age_hours=24)
        )

    def test_corrupt_file_is_quarantined_and_replaced(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{bad", encoding="utf-8")
        self.store.set_entry(self.path, "x", {"ok": True})
        self.assertEqual(
            {"ok": True},
            self.store.get_entry(self.path, "x", max_age_hours=24),
        )
        self.assertEqual(
            1,
            len(list(self.path.parent.glob("123.json.corrupt-*"))),
        )

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.entity_path("players", "..", "secret.json")


if __name__ == "__main__":
    unittest.main()
