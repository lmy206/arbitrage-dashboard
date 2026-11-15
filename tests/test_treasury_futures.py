import copy
from pathlib import Path
import sys
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater
from scripts.treasury_futures import balance_dv01, build_quarter_ratios, quarter_ratios_complete, verified_contract_dv01


class TreasuryFuturesTests(unittest.TestCase):
    def setUp(self):
        self.asof = pd.Timestamp("2026-11-13")
        self.dates = pd.to_datetime(["2026-11-12", "2026-11-13"])
        self.months = {"TL00.IF": {}, "T00.IF": {}}
        self.histories = {}
        for expiry in ("2611", "2612", "2703", "2706"):
            for root, prices in (("TL", [120, 121]), ("T", [100, 100])):
                symbol = f"{root}{expiry}.IF"
                self.months[f"{root}00.IF"][expiry] = symbol
                self.histories[symbol] = pd.DataFrame({"close": prices, "volume": [0, 0]}, index=self.dates)
        self.risk = {"source": "xtdata", "unit": "CNY/contract/bp", "status": "verified", "dataDate": "2026-11-13", "contracts": {
            "TL2612.IF": {"ctdSymbol": "fixture-long", "ctdDv01PerLot": 2240, "conversionFactor": 0.8, "dv01PerLot": 2800},
            "T2612.IF": {"ctdSymbol": "fixture-short", "ctdDv01PerLot": 900, "conversionFactor": 0.9, "dv01PerLot": 1000},
        }}

    def test_quarters_use_tl_divided_by_t_and_keep_zero_volume_months(self):
        rows = build_quarter_ratios(self.months, self.histories, self.asof)
        self.assertEqual([r["expiry"] for r in rows], ["2612", "2703", "2706"])
        self.assertEqual([r["current"] for r in rows], ["1.2100"] * 3)
        self.assertEqual(rows[0]["change"], "+0.0100")
        self.assertEqual(rows[0]["leftVolume"], 0)
        self.assertTrue(quarter_ratios_complete(rows, "2026-11-13"))

    def test_dv01_balancing_is_risk_weighted_not_value_weighted(self):
        result = balance_dv01(2800, 1000)
        self.assertEqual(result["lots"], "5:14")
        self.assertEqual(result["dv01DeviationPct"], 0)
        rows = build_quarter_ratios(self.months, self.histories, self.asof, self.risk)
        self.assertEqual(rows[0]["hedge"]["lots"], "5:14")
        self.assertTrue(quarter_ratios_complete(rows, "2026-11-13"))
        with self.assertRaisesRegex(ValueError, "DV01"):
            updater.balance_metrics("TL00.IF", "T00.IF", 121, 100)

    def test_missing_stale_or_inconsistent_ctd_data_never_falls_back_to_notional(self):
        for risk in (None, {**self.risk, "dataDate": "2026-11-12"}):
            rows = build_quarter_ratios(self.months, self.histories, self.asof, risk)
            self.assertTrue(all(r["hedge"]["status"] == "xtdata_unavailable" for r in rows))
            self.assertTrue(all(r["hedge"]["lots"] == "待DV01" for r in rows))
        invalid = copy.deepcopy(self.risk)
        invalid["contracts"]["TL2612.IF"]["conversionFactor"] = 0.9
        self.assertIsNone(verified_contract_dv01(invalid, "TL2612.IF", "2026-11-13"))
        self.assertIsNone(verified_contract_dv01({**self.risk, "unit": "per100"}, "TL2612.IF", "2026-11-13"))
        with self.assertRaises(ValueError):
            balance_dv01(float("nan"), 100)

    def test_future_prices_do_not_change_the_current_quarter_ratio(self):
        baseline = build_quarter_ratios(self.months, self.histories, self.asof)
        self.histories["TL2612.IF"].loc[pd.Timestamp("2026-11-16")] = [999, 999]
        self.assertEqual(build_quarter_ratios(self.months, self.histories, self.asof), baseline)

    def test_incomplete_quotes_are_explicit_and_do_not_invent_a_ratio(self):
        del self.histories["T2706.IF"]
        rows = build_quarter_ratios(self.months, self.histories, self.asof)
        self.assertEqual(rows[-1]["priceStatus"], "unavailable")
        self.assertIsNone(rows[-1]["ratio"])
        self.assertEqual(rows[-1]["current"], "—")
        self.assertTrue(quarter_ratios_complete(rows, "2026-11-13"))

    def test_treasury_futures_are_not_classified_as_stock_index_futures(self):
        self.assertFalse(updater.is_equity_index_definition({"left": "TL00.IF", "right": "T00.IF"}))
        self.assertTrue(updater.is_equity_index_definition({"left": "IM00.IF", "right": "IF00.IF"}))

    def test_leg_returns_and_pairable_volume_follow_dv01_quantities(self):
        self.histories["TL2612.IF"]["volume"] = [100, 100]
        self.histories["T2612.IF"]["volume"] = [210, 210]
        rows = build_quarter_ratios(self.months, self.histories, self.asof, self.risk)
        self.assertAlmostEqual(rows[0]["leftChangePct"], (121 / 120 - 1) * 100, places=5)
        self.assertEqual(rows[0]["rightChangePct"], 0)
        self.assertEqual(rows[0]["pairedVolume"], 15)
        self.assertIsNone(rows[1]["pairedVolume"])

    def test_same_month_full_daily_statistics_and_history_are_available(self):
        previous_dates = pd.to_datetime(["2025-11-12", "2025-11-13"])
        self.histories["TL2512.IF"] = pd.DataFrame({"close": [130, 140], "volume": [10, 10]}, index=previous_dates)
        self.histories["T2512.IF"] = pd.DataFrame({"close": [100, 100], "volume": [10, 10]}, index=previous_dates)
        rows = build_quarter_ratios(self.months, self.histories, self.asof)
        updater.enrich_treasury_statistics(rows, self.histories)
        current = rows[0]
        self.assertEqual(current["statisticsStatus"], "ok")
        self.assertEqual(current["percentile"], 50)
        self.assertEqual(current["signal"], "中性")
        self.assertEqual(current["historyChart"]["unit"], "比值")
        self.assertEqual(current["historyChart"]["statisticsPointCount"], 4)
        self.assertEqual(current["historyChart"]["series"][-1]["expiry"], "2612")


if __name__ == "__main__":
    unittest.main()
