"""Testes das métricas económicas puras do backtest, sem rede."""

import unittest

from src.backtest import _max_drawdown, _return_summary, _wilson_interval


class BacktestMetricTests(unittest.TestCase):
    def test_return_and_drawdown(self):
        result = _return_summary([1.0, -1.0, -1.0, 2.0])
        self.assertEqual(result["bets"], 4)
        self.assertEqual(result["profit_units"], 1.0)
        self.assertEqual(result["roi_pct"], 25.0)
        self.assertEqual(result["max_drawdown_units"], 2.0)

    def test_wilson_interval_contains_observed_rate(self):
        low, high = _wilson_interval(60, 100)
        self.assertLess(low, 0.6)
        self.assertGreater(high, 0.6)

    def test_empty_metrics_are_safe(self):
        self.assertEqual(_return_summary([])["roi_pct"], 0.0)
        self.assertEqual(_max_drawdown([]), 0.0)


if __name__ == "__main__":
    unittest.main()
