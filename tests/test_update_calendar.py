"""Calendar and configuration regressions use fixtures, never today's date."""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class UpdateCalendarTests(unittest.TestCase):
    def test_long_domestic_holiday_remains_fresh_until_market_reopens(self):
        calendar = pd.to_datetime(["2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09"])
        self.assertTrue(updater.domestic_data_is_fresh("2026-09-30", calendar, datetime(2026, 10, 7, 20, 10)))
        self.assertFalse(updater.domestic_data_is_fresh("2026-09-30", calendar, datetime(2026, 10, 8, 20, 10)))
        self.assertTrue(updater.domestic_data_is_fresh("2026-10-08", calendar, datetime(2026, 10, 8, 20, 10)))

    def test_month_end_calendar_request_cannot_follow_a_stale_series(self):
        for stale, now, expected in [
            ("2026-10-30", datetime(2026, 11, 5, 20, 10), "20261130"),
            ("2026-12-31", datetime(2027, 1, 4, 20, 10), "20270131"),
            ("2028-02-01", datetime(2028, 2, 29, 20, 10), "20280229"),
        ]:
            with self.subTest(now=now):
                self.assertEqual(updater.trading_calendar_end_date(pd.Timestamp(stale), now), expected)

    def test_cutoff_weekend_and_year_change_use_the_available_calendar(self):
        calendar = pd.to_datetime(["2026-12-31", "2027-01-04", "2027-01-05"])
        for now, expected in [
            (datetime(2027, 1, 3, 20, 10), "2026-12-31"),
            (datetime(2027, 1, 4, 19, 59), "2026-12-31"),
            (datetime(2027, 1, 4, 20, 0), "2027-01-04"),
        ]:
            self.assertEqual(updater.expected_domestic_data_date(calendar, now), pd.Timestamp(expected))
        self.assertFalse(updater.domestic_data_is_fresh("2027-01-05", calendar, datetime(2027, 1, 4, 20, 10)))

    def test_quarter_and_decade_roll_without_fixed_delivery_years(self):
        for date, down, skip in [
            ("2026-11-05", "2703", "2706"),
            ("2026-12-31", "2703", "2706"),
            ("2027-02-01", "2706", "2709"),
        ]:
            self.assertEqual(updater.im_down_quarter_period(pd.Timestamp(date)).strftime("%y%m"), down)
            self.assertEqual(updater.im_skip_quarter_period(pd.Timestamp(date)).strftime("%y%m"), skip)
        self.assertEqual(updater.normalize_expiry("001", pd.Timestamp("2029-12-01")), "3001")
        self.assertEqual(updater.normalize_expiry("3012", pd.Timestamp("2030-01-01")), "3012")
        self.assertEqual(updater.seasonal_expiries("3001")[-1], "3001")

    def test_since_listing_chart_does_not_lose_its_start_after_ten_years(self):
        definition = next(d for d in updater.PAIRS if d["pair"] == "铝合金-沪铝价差")
        dates = pd.to_datetime(["2025-06-10", "2025-06-11", "2036-11-05"])
        values = pd.Series([-600.0, -590.0, -580.0], index=dates)
        chart = updater.build_observation_history_chart(definition, "加权", definition["left"], definition["right"], values, dates[-1])
        self.assertEqual(chart["startDate"], "2025-06-10")
        self.assertEqual(chart["statisticsPointCount"], len(values))

    def test_named_contract_matches_configuration_and_rejects_missing_duplicate_sources(self):
        updater.validate_update_configuration()
        symbols = list(updater.DATA_CONTRACT["domesticSymbols"])
        self.assertTrue(updater.configured_members_complete(symbols, "domesticSymbols"))
        self.assertFalse(updater.configured_members_complete(symbols[:-1], "domesticSymbols"))
        self.assertFalse(updater.configured_members_complete(symbols[:-1] + [symbols[0]], "domesticSymbols"))
        with patch.object(updater, "PAIRS", updater.PAIRS[:-1]):
            with self.assertRaises(RuntimeError):
                updater.validate_update_configuration()


if __name__ == "__main__":
    unittest.main()
