"""Regression checks for rolling full-daily chart statistics, without live data."""

import statistics
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class ChartStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.definition = next(item for item in updater.PAIRS if item["pair"] == "油/粕比价")
        self.asof = pd.Timestamp("2026-11-05")
        self.dates = pd.bdate_range(end=self.asof, periods=120)
        self.values = pd.Series([1 + index / 1000 for index in range(120)], index=self.dates)
        # Older Tuesday spikes disappear from Friday chart sampling, but must
        # remain in the complete daily sample used for quantiles.
        spike_dates = [date for date in self.dates[:80] if date.weekday() == 1][:8]
        self.values.loc[spike_dates] = 9.0

    def chart(self, values=None, asof=None):
        values = self.values if values is None else values
        histories = {
            "y2705.DF": pd.DataFrame({"close": values * 1000}),
            "m2705.DF": pd.DataFrame({"close": pd.Series(1000.0, index=values.index)}),
        }
        return updater.build_contract_history_chart(self.definition, "2705", histories, asof or self.asof)

    def assert_daily_quantiles(self, chart, values):
        expected = statistics.quantiles(list(values), n=100, method="inclusive")
        self.assertEqual(chart["statisticsPointCount"], len(values))
        self.assertEqual(chart["quantileThresholds"], [
            {"label": "3%", "value": round(expected[2], 6)},
            {"label": "97%", "value": round(expected[96], 6)},
        ])

    def test_thresholds_include_daily_extremes_discarded_from_chart(self):
        chart = self.chart()
        self.assert_daily_quantiles(chart, self.values)
        plotted = [point["value"] for series in chart["series"] for point in series["points"]]
        self.assertLess(len(plotted), len(self.values))
        self.assertLess(max(plotted), 2)
        self.assertEqual(chart["quantileThresholds"][1]["value"], 9.0)

    def test_new_trading_days_can_change_thresholds(self):
        before = self.chart()
        new_dates = pd.bdate_range(start=self.asof + pd.Timedelta(days=1), periods=5)
        updated = pd.concat([self.values, pd.Series(20.0, index=new_dates)])
        after = self.chart(updated, new_dates[-1])
        self.assert_daily_quantiles(before, self.values)
        self.assert_daily_quantiles(after, updated)
        self.assertNotEqual(before["quantileThresholds"], after["quantileThresholds"])
        self.assertEqual(after["endDate"], new_dates[-1].strftime("%Y-%m-%d"))

    def test_equal_compact_and_daily_quantiles_are_valid(self):
        constant = pd.Series(3.0, index=self.dates)
        chart = self.chart(constant)
        self.assert_daily_quantiles(chart, constant)
        self.assertLess(chart["renderPointCount"], chart["statisticsPointCount"])
        self.assertEqual(chart["quantileThresholds"][1]["value"], 3.0)
        self.assertTrue(all(point["value"] == 3 for series in chart["series"] for point in series["points"]))

    def test_future_quotes_cannot_change_current_thresholds(self):
        future = pd.concat([self.values, pd.Series([1000.0], index=[self.asof + pd.Timedelta(days=1)])])
        chart = self.chart(future)
        self.assert_daily_quantiles(chart, self.values)
        self.assertEqual(chart, self.chart())


if __name__ == "__main__":
    unittest.main()
