"""Audit additions: temporal gates, paired samples and unchanged legacy metrics."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src import audit_observability as audit, dashboard, run_metrics
from src.llm_provider import AnthropicProvider, DisabledProvider, PaidLLMDisabledError
from scripts.refresh_observability import refresh
from tests import test_dashboard as dashboard_fixtures


def fixtures(outcome='a'):
    s = {'key': 'atp:1', 'event_key': 'atp:1', 'player_a': {'id': 1}, 'player_b': {'id': 2},
         'analyzed_at_utc': '2026-09-08T10:01:00Z', 'commence_time_utc': '2026-09-08T12:00:00Z',
         'entry_market_observation_id': 'quote', 'odds_provenance': {'captured_at_utc': '2026-09-08T10:00:00Z',
         'bookmaker': 'BOOK', 'endpoint': 'ENDPOINT'}, 'pricing': {'available': True,
         'model_version': 'v1', 'configuration_fingerprint': 'config',
         'market_probability_a': .5, 'market_probability_b': .5,
         'sharp_estimate_a': .6, 'sharp_estimate_b': .4, 'market_odd_a': 1.9, 'market_odd_b': 1.9},
         'outcome': {'winner_side': outcome}}
    o = {'observation_id': 'quote', 'eligibility': {'market_memory': True},
         'event': {'event_key': 'atp:1', 'scheduled_start_utc': s['commence_time_utc'],
                   'player_a': {'id': 1}, 'player_b': {'id': 2}},
         'capture': {'captured_at_utc': s['odds_provenance']['captured_at_utc'], 'identity_mapping_status': 'VERIFIED'},
         'source': {'bookmaker': 'BOOK', 'endpoint': 'ENDPOINT'}, 'market': {'type': 'MONEYLINE'},
         'selections': [{'side': 'a', 'raw_decimal_odd': 1.9}, {'side': 'b', 'raw_decimal_odd': 1.9}]}
    return s, o


class AuditTests(unittest.TestCase):
    def test_missing_sources_are_not_zero(self):
        self.assertIsNone(audit.paired_comparison(None, [])['sample_size'])
        self.assertEqual(audit.paired_comparison([], [])['sample_size'], 0)

    def test_pairs_have_equal_samples_and_correct_scores(self):
        s, o = fixtures()
        r = audit.paired_comparison([s], [o])
        self.assertEqual(r['market']['sample_size'], r['fenzobot']['sample_size'])
        self.assertEqual(r['market']['brier_score'], .25)
        self.assertEqual(r['fenzobot']['brier_score'], .16)
        self.assertEqual(r['delta']['brier_score'], -.09)
        self.assertEqual(r['mode'], 'RETROSPECTIVE_DESCRIPTIVE')

    def test_outcome_does_not_change_eligibility(self):
        s, o = fixtures()
        before = audit.paired_comparison([s], [o])
        for result in ('b', None):
            s['outcome']['winner_side'] = result
            after = audit.paired_comparison([s], [o])
            self.assertEqual(before['eligibility_hash'], after['eligibility_hash'])
            self.assertEqual(before['eligible_forecasts'], after['eligible_forecasts'])
        self.assertEqual(after['sample_size'], 0)
        self.assertEqual(after['pending_or_unresolved'], 1)

    def test_closed_future_market_does_not_change_pair(self):
        s, o = fixtures()
        future = copy.deepcopy(o)
        future['observation_id'] = 'closing'
        future['capture']['captured_at_utc'] = '2026-09-08T12:01:00Z'
        self.assertEqual(audit.paired_comparison([s], [o]), audit.paired_comparison([s], [o, future]))

    def test_nonfinite_bool_and_incoherent_probabilities_fail(self):
        for val in (float('nan'), float('inf'), True, -.1, 1.0, .7):
            s, o = fixtures()
            s['pricing']['sharp_estimate_a'] = val
            self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)

    def test_temporal_order_and_timezone_fail_closed(self):
        for at in ('2026-09-08T12:00:00Z', '2026-09-08T09:59:00Z', '2026-09-08T10:01:00', None):
            s, o = fixtures()
            s['analyzed_at_utc'] = at
            self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)

    def test_wrong_link_house_side_and_start_rejected(self):
        for part, key, val in [('event', 'event_key', 'atp:2'), ('event', 'scheduled_start_utc', '2026-09-09T12:00:00Z'),
                               ('source', 'bookmaker', 'OTHER'), ('capture', 'identity_mapping_status', 'UNKNOWN')]:
            s, o = fixtures()
            o[part][key] = val
            self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)
        s, o = fixtures()
        o['event']['player_a']['id'] = 2
        self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)

    def test_different_raw_odds_rejected(self):
        s, o = fixtures()
        s['pricing']['market_odd_a'] = 2.0
        self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)

    def test_market_probability_must_match_frozen_odds(self):
        s, o = fixtures()
        s['pricing'].update(market_probability_a=.6, market_probability_b=.4)
        self.assertEqual(audit.paired_comparison([s], [o])['eligible_forecasts'], 0)

    def test_duplicates_not_independent_samples(self):
        s, o = fixtures()
        r = audit.paired_comparison([s, copy.deepcopy(s)], [o])
        self.assertEqual(r['eligible_forecasts'], 0)
        self.assertEqual(r['exclusions']['DUPLICATE_IDENTITY'], 2)

    def test_conflicting_observation_ids_rejected(self):
        s, o = fixtures()
        other = copy.deepcopy(o)
        other['source']['bookmaker'] = 'OTHER'
        self.assertEqual(audit.paired_comparison([s], [o, other])['eligible_forecasts'], 0)

    def test_no_mutation(self):
        s, o = fixtures()
        before = copy.deepcopy((s, o))
        audit.paired_comparison([s], [o])
        self.assertEqual(before, (s, o))

    def test_legacy_green_remains_unclassified(self):
        s, _ = fixtures()
        s['analysis'] = {'flag': '🟢'}
        d = audit.green_diagnostics([s])
        self.assertEqual(d['prospectively_classified'], 0)
        self.assertEqual(d['legacy_or_not_prospective'], 1)

    def test_existing_reason_codes_counted_without_reclassification(self):
        s, _ = fixtures()
        s['validation'] = {'cohorts': {'GREEN_STRONG_V1': {'prospective': True, 'eligible': False,
                            'reason_codes': ['PAPER_NOT_ELIGIBLE', 'PAPER_NOT_ELIGIBLE']}}}
        d = audit.green_diagnostics([s])
        self.assertEqual(d['exclusion_reason_counts'], {'PAPER_NOT_ELIGIBLE': 1})
        self.assertEqual(d['eligible'], 0)

    def test_legacy_dashboard_fields_identical_with_extension(self):
        fixture = dashboard_fixtures.DashboardTests()
        fixture.setUp()
        try:
            fixture._base_sources()
            with patch('src.audit_observability.build', return_value={}):
                old = fixture.build()
            new = fixture.build()
            for v in (old, new):
                v.pop('audit_v1');v.pop('semantic_fingerprint')
            self.assertEqual(old, new)
        finally:
            fixture.tearDown()

    def test_html_has_accessible_legacy_metrics_and_new_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = dashboard.render_dashboard_html(dashboard.build_dashboard(root=Path(tmp)))
        for marker in ('Ver todas as métricas', 'mesma amostra', 'legacyGlobalView', 'System Health',
                       'minimumFractionDigits:6', 'Publicação: N/D', 'não é OOS primário'):
            self.assertIn(marker, html)

    def test_refresh_does_not_settle_and_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.market_memory_report.build_and_write', side_effect=ValueError('bad ledger')):
            result = refresh(Path(tmp))
            self.assertEqual(result['market_memory'], 'ValueError')
            self.assertEqual(result['dashboard'], 'AVAILABLE')
            self.assertFalse((Path(tmp)/'data/paper_trades.json').exists())
            self.assertFalse((Path(tmp)/'data/calibration_snapshots.json').exists())

    def test_disabled_provider_has_zero_external_requests(self):
        run_metrics.reset()
        DisabledProvider().generate(system_prompt='', user_prompt='', max_tokens=1)
        self.assertEqual(run_metrics.snapshot()['llm_external_requests'], 0)

    def test_guarded_provider_never_counts_a_request(self):
        run_metrics.reset()
        with self.assertRaises(PaidLLMDisabledError):
            AnthropicProvider(allow_paid=False).generate(system_prompt='', user_prompt='', max_tokens=1)
        self.assertEqual(run_metrics.snapshot()['llm_external_requests'], 0)

    def test_sdk_request_counted_once_with_mock_client(self):
        run_metrics.reset()
        provider = AnthropicProvider(allow_paid=True)
        client = MagicMock()
        client.messages.create.return_value.content = []
        with patch.object(provider, '_get_client', return_value=client):
            provider.generate(system_prompt='', user_prompt='', max_tokens=1)
        self.assertEqual(run_metrics.snapshot()['llm_external_requests'], 1)
