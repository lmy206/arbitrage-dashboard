import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class TreasuryYieldSpreadTests(unittest.TestCase):
    def setUp(self):
        self.definition = next(d for d in updater.PAIRS if d["pair"] == "TL-T利率差")
        self.asof = pd.Timestamp("2026-11-13")
        self.dates = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"])
        self.external = {
            updater.CN30Y_SYMBOL: pd.Series([2.4, 2.5, 2.3, 2.2], index=self.dates),
            updater.CN10Y_SYMBOL: pd.Series([2.0, 2.0, 2.0, 2.0], index=self.dates),
        }

    def build(self):
        row, date = updater.build_external_reference_row(self.definition, {}, self.external, self.asof)
        row["marketCategory"] = updater.market_category_for_definition(self.definition)
        return row, date

    def test_long_minus_short_yield_is_converted_from_percent_to_bp(self):
        row, date = self.build()
        expected = (Decimal("2.2") - Decimal("2.0")) * 100
        self.assertEqual(row["yieldSpreadBp"], float(expected))
        self.assertEqual(row["current"], "20.00bp")
        self.assertEqual(row["previous"], "30.00bp")
        self.assertEqual(row["change"], "-10.00bp")
        self.assertEqual(date, self.asof)
        self.assertTrue(updater.treasury_yield_spread_row_complete(row, "2026-11-13"))
        self.assertEqual(row["mainHistoryChart"]["unit"], "基点")
        self.assertEqual(row["referenceFutures"], ["TL", "T"])
        self.assertTrue(all(row[key] == "—" for key in ("lots", "notional", "margin")))

    def test_flat_or_inverted_yield_curve_is_a_valid_spread(self):
        self.external[updater.CN30Y_SYMBOL] = pd.Series([2.4, 2.5, 2.0, 1.9], index=self.dates)
        row, _ = self.build()
        self.assertEqual(row["current"], "-10.00bp")
        self.assertEqual(row["previous"], "0.00bp")
        self.assertTrue(updater.treasury_yield_spread_row_complete(row, "2026-11-13"))

    def test_missing_maturity_dates_use_only_the_latest_common_day(self):
        self.external[updater.CN30Y_SYMBOL] = self.external[updater.CN30Y_SYMBOL].drop(self.dates[-1])
        self.external[updater.CN10Y_SYMBOL] = self.external[updater.CN10Y_SYMBOL].drop(self.dates[-2])
        row, date = self.build()
        self.assertEqual(date, self.dates[1])
        self.assertEqual(row["current"], "50.00bp")
        self.assertEqual(set(row["externalSourceDates"].values()), {"2026-11-11"})
        self.assertTrue(updater.treasury_yield_spread_row_complete(row, "2026-11-13"))

    def test_future_yields_cannot_change_current_rank_or_chart(self):
        baseline, _ = self.build()
        for symbol in self.external:
            self.external[symbol].loc[pd.Timestamp("2026-11-16")] = 99.0
        actual, _ = self.build()
        self.assertEqual(actual, baseline)

    def test_equal_spreads_remain_ties_before_percentiles(self):
        self.external[updater.CN30Y_SYMBOL] = pd.Series([1.8, 2.0, 2.2, 2.4], index=self.dates)
        self.external[updater.CN10Y_SYMBOL] = pd.Series([1.3, 1.5, 1.7, 1.9], index=self.dates)
        row, _ = self.build()
        self.assertEqual(row["allTime"], "100.00%")
        self.assertEqual(row["change"], "+0.00bp")
        self.assertEqual({p["value"] for p in row["mainHistoryChart"]["series"][0]["points"]}, {50.0})

    def test_duplicate_or_stale_common_dates_fail(self):
        duplicate = pd.concat([self.external[updater.CN30Y_SYMBOL], self.external[updater.CN30Y_SYMBOL].tail(1)])
        with self.assertRaises(updater.ExternalDataError):
            updater.align_treasury_yields(duplicate, self.external[updater.CN10Y_SYMBOL], self.asof)
        with self.assertRaises(updater.ExternalDataError):
            updater.align_treasury_yields(self.external[updater.CN30Y_SYMBOL], self.external[updater.CN10Y_SYMBOL], pd.Timestamp("2026-11-25"))

    def test_integrity_rejects_wrong_units_dates_sign_and_invented_lots(self):
        baseline, _ = self.build()
        for field, value in [("yieldSpreadBp", 0.2), ("yieldSpreadBp", -20), ("current", "0.20%"), ("lots", "1:1")]:
            row = copy.deepcopy(baseline)
            row[field] = value
            self.assertFalse(updater.treasury_yield_spread_row_complete(row, "2026-11-13"), field)
        row = copy.deepcopy(baseline)
        row["externalSourceDates"][updater.CN10Y_SYMBOL] = "2026-11-12"
        self.assertFalse(updater.treasury_yield_spread_row_complete(row, "2026-11-13"))

    def test_curve_normalization_selects_the_government_curve_and_requested_tenor(self):
        raw = pd.DataFrame({"曲线名称": ["中债国债收益率曲线", "中债商业银行普通债收益率曲线(AAA)"],
                            "日期": ["2026-11-13", "2026-11-13"], "10年": [2.0, 3.0], "30年": [2.2, 4.0]})
        ten = updater.normalize_chinabond_yield(raw, "10年")
        thirty = updater.normalize_chinabond_yield(raw, "30年")
        self.assertEqual(ten["close"].tolist(), [2.0])
        self.assertEqual(thirty["close"].tolist(), [2.2])
        with self.assertRaises(ValueError):
            updater.normalize_chinabond_yield(raw, "50年")


if __name__ == "__main__":
    unittest.main()
