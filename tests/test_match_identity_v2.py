import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src import (
    calibration_store,
    dashboard,
    main,
    market_integrity,
    market_ledger,
    match_identity_v2 as identity,
    paper_trading,
    report_html,
    telegram_summary,
)


class MatchIdentityV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.registry = root / "registry-v2.json"
        self.events = root / "events-v2.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def observation(**overrides):
        value = {
            "id": 501,
            "_tour": "wta",
            "tournamentId": 77,
            "roundId": None,
            "date": "2026-09-22T12:00:00+00:00",
            "player1Id": 10,
            "player2Id": 20,
            "player1": {"id": 10, "name": "Alpha One"},
            "player2": {"id": 20, "name": "Beta Two"},
        }
        value.update(overrides)
        return value

    def resolve(self, observation=None, **kwargs):
        return identity.resolve_observation(
            observation or self.observation(),
            registry_path=self.registry,
            events_path=self.events,
            observed_at_utc=kwargs.pop("observed_at_utc", "2026-09-22T08:00:00+00:00"),
            **kwargs,
        )

    def test_same_match_id_different_pairs_mint_distinct_instances_without_overwrite(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        second_match = self.observation(
            player1Id=30, player2Id=40,
            player1={"id": 30, "name": "Gamma"},
            player2={"id": 40, "name": "Delta"},
        )
        second = self.resolve(second_match, event_id="event-b", event_id_validated=True)
        self.assertNotEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])
        registry = identity.read_registry(self.registry)
        match_aliases = [row for row in registry["aliases"] if row["alias_type"] == identity.ALIAS_MATCH_ID]
        self.assertEqual(len(match_aliases), 2)
        self.assertEqual({row["alias_value"] for row in match_aliases}, {"501"})

    def test_same_event_and_context_with_different_match_ids_resolves_same_instance(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        rerun = self.observation(id=999, date="2026-09-23T12:00:00+00:00")
        second = self.resolve(rerun, event_id="event-a", event_id_validated=True)
        self.assertEqual(second["identity_status"], identity.CANONICAL_RESOLVED)
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])

    def test_alias_namespace_includes_provider_without_reminting_unique_structure(self):
        first = self.resolve(event_id="shared-value", event_id_validated=True, provider="Provider A")
        second = self.resolve(
            self.observation(id=999),
            event_id="shared-value",
            event_id_validated=True,
            provider="Provider B",
        )
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])
        registry = identity.read_registry(self.registry)
        event_aliases = [row for row in registry["aliases"] if row["alias_type"] == identity.ALIAS_EVENT_ID]
        self.assertEqual({row["provider"] for row in event_aliases}, {"Provider A", "Provider B"})

    def test_same_event_with_different_players_conflicts_and_does_not_reassign(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        incompatible = self.observation(
            player1Id=30, player2Id=40,
            player1={"id": 30, "name": "Gamma"},
            player2={"id": 40, "name": "Delta"},
        )
        conflict = self.resolve(incompatible, event_id="event-a", event_id_validated=True)
        self.assertEqual(conflict["identity_status"], identity.IDENTITY_CONFLICT)
        self.assertIsNone(conflict["canonical_match_instance_id"])
        registry = identity.read_registry(self.registry)
        self.assertEqual(len(registry["instances"]), 1)
        self.assertEqual(registry["instances"][0]["canonical_match_instance_id"], first["canonical_match_instance_id"])
        self.assertEqual(registry["aliases"][0]["status"], identity.ALIAS_CONFLICTED)
        payload = self._canonical_payload()
        self.assertEqual(payload["identity_status"], identity.IDENTITY_CONFLICT)
        self.assertEqual(paper_trading.build_entries(payload), [])

    def test_player_orientation_reschedule_and_date_change_do_not_change_identity(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        inverted = self.observation(
            id=777,
            date="2026-09-23T12:00:00+00:00",
            player1Id=20, player2Id=10,
            player1={"id": 20, "name": "Beta Two"},
            player2={"id": 10, "name": "Alpha One"},
        )
        second = self.resolve(inverted, event_id="event-a", event_id_validated=True)
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])
        self.assertEqual(second["identity_evidence"]["orientation"], {"a": 20, "b": 10})

    def test_one_hour_reschedule_does_not_change_identity(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        second = self.resolve(
            self.observation(id=999, date="2026-09-22T13:00:00+00:00"),
            event_id="event-a",
            event_id_validated=True,
        )
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])

    def test_round_missing_then_appears_does_not_remint(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        second = self.resolve(self.observation(roundId=4), event_id="event-a", event_id_validated=True)
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])

    def test_event_id_can_enrich_round_minted_instance_without_remint(self):
        first = self.resolve(self.observation(roundId=4))
        second = self.resolve(self.observation(roundId=4), event_id="event-a", event_id_validated=True)
        self.assertEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])
        self.assertEqual(second["identity_status"], identity.CANONICAL_RESOLVED)

    def test_structure_without_strong_discriminator_is_provisional(self):
        result = self.resolve()
        self.assertEqual(result["identity_status"], identity.IDENTITY_PROVISIONAL)
        self.assertIsNone(result["canonical_match_instance_id"])
        self.assertFalse(self.registry.exists())

    def test_names_and_time_without_player_ids_are_insufficient(self):
        value = self.observation(player1Id=None, player2Id=None)
        value["player1"] = {"name": "Alpha One"}
        value["player2"] = {"name": "Beta Two"}
        result = self.resolve(value, event_id="event-a", event_id_validated=True)
        self.assertEqual(result["identity_status"], identity.IDENTITY_INSUFFICIENT)

    def test_similar_names_never_override_divergent_player_ids(self):
        self.resolve(event_id="event-a", event_id_validated=True)
        value = self.observation(
            player1Id=999, player1={"id": 999, "name": "Alpha One"},
        )
        result = self.resolve(value, event_id="event-a", event_id_validated=True)
        self.assertEqual(result["identity_status"], identity.IDENTITY_CONFLICT)

    def test_different_tournament_mints_distinct_instance(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        second = self.resolve(
            self.observation(tournamentId=88), event_id="event-b", event_id_validated=True,
        )
        self.assertNotEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])

    def test_same_structure_with_distinct_bound_event_ids_mints_distinct_instances(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        second = self.resolve(self.observation(id=502), event_id="event-b", event_id_validated=True)
        self.assertNotEqual(first["canonical_match_instance_id"], second["canonical_match_instance_id"])

    def test_unverified_event_id_cannot_mint(self):
        result = self.resolve(event_id="event-a", event_id_validated=False)
        self.assertEqual(result["identity_status"], identity.IDENTITY_PROVISIONAL)

    def test_existing_match_alias_requires_structural_coherence(self):
        first = self.resolve(event_id="event-a", event_id_validated=True)
        rerun = self.resolve(self.observation(), event_id=None)
        self.assertEqual(rerun["canonical_match_instance_id"], first["canonical_match_instance_id"])
        incompatible = self.observation(
            player1Id=30, player2Id=40,
            player1={"id": 30, "name": "Gamma"},
            player2={"id": 40, "name": "Delta"},
        )
        unresolved = self.resolve(incompatible)
        self.assertEqual(unresolved["identity_status"], identity.IDENTITY_PROVISIONAL)

    def test_doubles_fail_closed(self):
        value = self.observation(
            player1={"id": 10, "name": "A One/B Two"},
            player2={"id": 20, "name": "C Three/D Four"},
        )
        result = self.resolve(value, event_id="doubles", event_id_validated=True)
        self.assertEqual(result["identity_reason_code"], "UNSUPPORTED_DOUBLES_IDENTITY_V2")

    def test_concurrent_mint_creates_exactly_one_instance(self):
        barrier = threading.Barrier(2)
        results = []

        def worker():
            barrier.wait()
            results.append(self.resolve(event_id="event-a", event_id_validated=True))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len({row["canonical_match_instance_id"] for row in results}), 1)
        self.assertEqual(len(identity.read_registry(self.registry)["instances"]), 1)

    def test_registry_write_failure_returns_noncanonical_status(self):
        with patch.object(identity, "_write_registry", side_effect=OSError("disk full")):
            result = self.resolve(event_id="event-a", event_id_validated=True)
        self.assertEqual(result["identity_status"], identity.IDENTITY_INSUFFICIENT)
        self.assertFalse(result["identity_persisted"])
        self.assertIsNone(result["canonical_match_instance_id"])

    def test_registry_and_event_log_are_schema_valid_and_auditable(self):
        result = self.resolve(
            event_id="event-a", event_id_validated=True,
            runtime_metadata={"runtime_sha": "abc", "github_run_id": "123"},
        )
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        events = [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(registry["schema_version"], 2)
        self.assertEqual(registry["activation"]["runtime_sha"], "abc")
        self.assertEqual(registry["activation"]["github_run_id"], "123")
        self.assertEqual(events[0]["canonical_match_instance_id"], result["canonical_match_instance_id"])
        self.assertIn("INSTANCE_MINTED", {row["event_type"] for row in events})

    def test_read_only_settlement_requires_strong_alias_and_expected_instance(self):
        minted = self.resolve(event_id="event-a", event_id_validated=True)
        completed = self.observation()
        resolved = identity.resolve_existing(
            completed,
            minted["canonical_match_instance_id"],
            registry_path=self.registry,
        )
        self.assertEqual(resolved["status"], identity.CANONICAL_RESOLVED)
        wrong = identity.resolve_existing(
            self.observation(player1Id=30),
            minted["canonical_match_instance_id"],
            registry_path=self.registry,
        )
        self.assertEqual(wrong["status"], identity.IDENTITY_CONFLICT)
        wrong_event = identity.resolve_existing(
            self.observation(),
            minted["canonical_match_instance_id"],
            event_id="different-event",
            event_id_validated=True,
            registry_path=self.registry,
        )
        self.assertEqual(wrong_event["status"], identity.IDENTITY_INSUFFICIENT)
        self.assertEqual(wrong_event["reason_code"], "SETTLEMENT_EVENT_ALIAS_UNBOUND")

    def _canonical_payload(self):
        resolved = self.resolve(event_id="event-a", event_id_validated=True)
        captured = "2026-09-22T08:00:00+00:00"
        payload = {
            **resolved,
            "match_id": 501,
            "tour": "wta",
            "tournament_id": 77,
            "tournament": "Test Open",
            "player_a_id": 10,
            "player_b_id": 20,
            "player_a": "Alpha One",
            "player_b": "Beta Two",
            "commence_time_utc": "2026-09-22T12:00:00+00:00",
            "market_odds_decimal": {"Alpha One": 2.1, "Beta Two": 1.8},
            "odds_operational_pricing_eligible": True,
            "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
            "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
            "pricing": {
                "available": True,
                "model_version": "test-v1",
                "configuration_fingerprint": "test",
                "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
                "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
            },
            "prelive_decision": {
                "state": "EDGE_POSITIVE",
                "paper_eligible": True,
                "expected_edge_pct": 3.0,
                "player": "Alpha One",
                "odd": 2.1,
                "fair_odd": 2.0,
                "paper_markets": [{
                    "market_type": "Moneyline",
                    "market": "Moneyline Alpha One",
                    "side": "a",
                    "player": "Alpha One",
                    "odd": 2.1,
                }],
            },
            "report_id": "report-v2",
            "analyzed_at_utc": captured,
            "features": {},
        }
        payload["snapshot_key"] = resolved["canonical_match_instance_id"]
        payload["event_key"] = resolved["canonical_match_instance_id"]
        payload["snapshot_linkage"] = {
            "status": "LINKED",
            "reason_code": "CANONICAL_MATCH_INSTANCE_ID_MATCH",
        }
        return payload

    def test_v2_snapshot_uses_canonical_key_and_preserves_legacy_key(self):
        payload = self._canonical_payload()
        snapshot = calibration_store.build_snapshot(payload, {})
        self.assertEqual(snapshot["key"], payload["canonical_match_instance_id"])
        self.assertEqual(snapshot["event_key"], payload["canonical_match_instance_id"])
        self.assertEqual(snapshot["legacy_key"], "wta:501")

    def test_provisional_identity_creates_neither_snapshot_nor_paper(self):
        result = self.resolve()
        payload = self._canonical_payload()
        payload.update(result)
        payload["snapshot_key"] = None
        payload["snapshot_linkage"] = {"status": "UNLINKED"}
        main._apply_identity_persistence_gate(payload)
        self.assertEqual(payload["prelive_decision"]["state"], "EDGE_POSITIVE")
        self.assertFalse(payload["prelive_decision"]["paper_eligible"])
        self.assertEqual(payload["prelive_decision"]["paper_markets"], [])
        with self.assertRaisesRegex(ValueError, "identity_v2_not_canonical"):
            calibration_store.build_snapshot(payload, {})
        self.assertEqual(paper_trading.build_entries(payload), [])
        html = report_html.build_report_html_v2(payload, {}, lambda _payload: None)
        self.assertIn("IDENTIDADE AINDA NÃO ELEGÍVEL PARA PAPER", html)
        self.assertNotIn("EDGE POSITIVO — REGISTADO EM PAPER", html)
        _priority, icon, text = telegram_summary.decision_row(payload)
        self.assertEqual(icon, "🟡")
        self.assertIn("sem PAPER", text)

    def test_v2_paper_key_uses_canonical_identity_and_keeps_source_contract_gate(self):
        payload = self._canonical_payload()
        entry = paper_trading.build_entries(payload)[0]
        canonical_id = payload["canonical_match_instance_id"]
        self.assertTrue(entry["key"].startswith(f"{canonical_id}:moneyline:a:"))
        self.assertEqual(entry["pregame"]["event_key"], canonical_id)
        self.assertEqual(entry["pregame"]["legacy_key"], "wta:501")
        payload["pricing"]["odds_source_contract_fingerprint"] = "wrong"
        self.assertEqual(paper_trading.build_entries(payload), [])

    def test_registry_failure_cannot_create_paper(self):
        with patch.object(identity, "_write_registry", side_effect=OSError("disk full")):
            result = self.resolve(event_id="event-a", event_id_validated=True)
        payload = self._canonical_payload()
        payload.update(result)
        payload["snapshot_key"] = None
        self.assertEqual(paper_trading.build_entries(payload), [])

    def test_v2_ledger_keeps_canonical_and_legacy_keys(self):
        payload = self._canonical_payload()
        match = self.observation()
        match.update({key: payload[key] for key in (
            "identity_schema_version", "canonical_match_instance_id", "identity_status",
            "identity_reason_code", "legacy_key", "identity_evidence", "identity_persisted",
        )})
        observation = market_ledger.build_observation(
            match,
            {"Alpha One": 2.1, "Beta Two": 1.8},
            {
                "source": "RapidAPI Tennis API / recent-odds",
                "endpoint": "test",
                "event_id": "event-a",
                "captured_at_utc": "2026-09-22T08:00:00+00:00",
                "bookmaker": "Book A",
                "freshness_status": "OBSERVED_AT_CAPTURE_UNVERIFIED_AGE",
                "identity_mapping_status": "VERIFIED",
                "operational_pricing_eligible": True,
            },
            role="OPERATIONAL_PRICING",
            pipeline="PRELIVE",
        )
        self.assertEqual(observation["event"]["event_key"], payload["canonical_match_instance_id"])
        self.assertEqual(observation["event"]["legacy_event_key"], "wta:501")
        self.assertEqual(observation["identity"]["status"], identity.CANONICAL_STRONG)

    def test_provisional_ledger_is_observable_but_not_market_memory_eligible(self):
        match = self.observation()
        match.update(self.resolve())
        observation = market_ledger.build_observation(
            match,
            {"Alpha One": 2.1, "Beta Two": 1.8},
            {
                "source": "test",
                "endpoint": "test",
                "event_id": None,
                "captured_at_utc": "2026-09-22T08:00:00+00:00",
                "bookmaker": "Book A",
                "freshness_status": "FRESH",
                "identity_mapping_status": "VERIFIED",
                "operational_pricing_eligible": True,
            },
            role="OPERATIONAL_PRICING",
            pipeline="PRELIVE",
        )
        self.assertFalse(observation["eligibility"]["market_memory"])
        self.assertIn(
            "IDENTITY_NOT_CANONICAL:IDENTITY_PROVISIONAL",
            observation["eligibility"]["reasons"],
        )

    def test_v2_snapshot_and_paper_settle_only_through_same_instance(self):
        payload = self._canonical_payload()
        snapshot_path = Path(self.tmp.name) / "snapshots.json"
        paper_path = Path(self.tmp.name) / "paper.json"
        calibration_store.upsert_snapshots(
            [calibration_store.build_snapshot(payload, {})], snapshot_path,
        )
        paper_trading.append_entries(paper_trading.build_entries(payload), paper_path)
        completed = {
            **self.observation(),
            "eventId": "event-a",
            "match_winner": 10,
            "result_type": "completed",
            "result": "6-4 6-4",
        }
        self.assertEqual(calibration_store.settle_from_matches(
            [completed], snapshot_path, identity_registry_path=self.registry,
        ), 1)
        self.assertEqual(paper_trading.settle_from_matches(
            [completed], paper_path, identity_registry_path=self.registry,
        ), 1)

    def test_v2_ambiguous_settlement_fails_closed(self):
        payload = self._canonical_payload()
        paper_path = Path(self.tmp.name) / "paper.json"
        paper_trading.append_entries(paper_trading.build_entries(payload), paper_path)
        completed = {
            **self.observation(),
            "eventId": "event-a",
            "match_winner": 10,
            "result_type": "completed",
            "result": "6-4 6-4",
        }
        self.assertEqual(paper_trading.settle_from_matches(
            [completed, dict(completed)], paper_path, identity_registry_path=self.registry,
        ), 0)

    def test_public_report_exposes_state_but_never_canonical_id(self):
        payload = self._canonical_payload()
        html = report_html.build_report_html_v2(payload, {}, lambda _payload: None)
        self.assertIn('name="fenzobot-identity-schema-version" content="2"', html)
        self.assertIn('name="fenzobot-identity-status" content="CANONICAL_STRONG"', html)
        self.assertNotIn(payload["canonical_match_instance_id"], html)

    def test_dashboard_aggregates_v2_without_publishing_ids_or_merging_legacy(self):
        payload = self._canonical_payload()
        root = Path(self.tmp.name) / "dashboard"
        registry_path = root / identity.DEFAULT_REGISTRY_PATH
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(self.registry.read_text(encoding="utf-8"), encoding="utf-8")
        snapshot_path = root / "data/calibration_snapshots.json"
        calibration_store.upsert_snapshots([
            calibration_store.build_snapshot(payload, {}),
            calibration_store.build_snapshot({
                "match_id": "legacy", "tour": "atp", "tournament_id": 9,
                "player_a_id": 30, "player_b_id": 40,
                "player_a": "Legacy A", "player_b": "Legacy B",
            }, {}),
        ], snapshot_path)
        result = dashboard.build_dashboard(root=root, generated_at_utc="2026-09-22T09:00:00+00:00")
        panel = result["match_identity_v2"]
        self.assertEqual(panel["canonical_instances"], 1)
        self.assertEqual(panel["canonical_snapshots"], 1)
        self.assertNotIn(payload["canonical_match_instance_id"], json.dumps(result))

    def test_empty_activation_registry_contains_no_historical_identity(self):
        empty = identity._empty_registry()
        self.assertEqual(empty["instances"], [])
        self.assertEqual(empty["aliases"], [])
        self.assertIsNone(empty["activation"]["first_observed_at_utc"])


if __name__ == "__main__":
    unittest.main()
