import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class ContractSelectionTests(unittest.TestCase):
    def setUp(self):
        self.definition = dict(next(item for item in updater.PAIRS if item["pair"] == "铝合金-沪铝价差"))
        self.asof = pd.Timestamp("2026-09-23")
        self.dates = pd.to_datetime(["2026-09-22", "2026-09-23"])
        self.months = {"ad00.SF": {}, "al00.SF": {}}
        self.histories = {}
        for expiry, volume in [("2610", 0), ("2611", 10), ("2612", 20), ("2701", 30), ("2702", 100000), ("2705", 200000)]:
            for root, prices in [("ad", [23500.0, 23520.0]), ("al", [24100.0, 24110.0])]:
                symbol = f"{root}{expiry}.SF"
                self.months[f"{root}00.SF"][expiry] = symbol
                self.histories[symbol] = pd.DataFrame({"close": prices, "volume": [volume, volume]}, index=self.dates)

    def build(self, definition=None):
        return updater.build_contract_rows(definition or self.definition, self.histories, self.months, self.asof, include_history_chart=False)

    def test_nearest_four_override_far_month_liquidity_and_keep_zero_volume(self):
        rows = self.build()
        self.assertEqual([row["expiry"] for row in rows], ["2610", "2611", "2612", "2701"])
        self.assertEqual(rows[0]["pairedVolume"], 0)
        self.assertEqual(rows[0]["current"], "-590")
        self.assertTrue(all(row["lots"] == "1:2" for row in rows))

    def test_both_legs_and_current_date_are_required(self):
        del self.months["al00.SF"]["2611"]
        self.histories["ad2610.SF"] = self.histories["ad2610.SF"].iloc[:1]
        rows = self.build()
        self.assertEqual([row["expiry"] for row in rows], ["2612", "2701", "2702", "2705"])

    def test_default_liquidity_selection_is_preserved(self):
        definition = {**self.definition, "contract_selection": "liquidity"}
        rows = self.build(definition)
        self.assertEqual([row["expiry"] for row in rows], ["2612", "2701", "2702", "2705"])
        self.assertTrue(all(row["pairedVolume"] > 0 for row in rows))


if __name__ == "__main__":
    unittest.main()
