import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class DisplayedTermStructureTests(unittest.TestCase):
    def setUp(self):
        self.asof = pd.Timestamp("2026-10-26")
        self.histories = {}
        for expiry, price in [("2611", 3089), ("2701", 3037), ("2705", 3050), ("2710", 3081)]:
            self.histories[f"rb{expiry}.SF"] = pd.DataFrame(
                {"close": [price], "volume": [1000000 if expiry == "2611" else 0]}, index=[self.asof]
            )

    def classify(self, months):
        contracts = [{"expiry": month, "leftSymbol": f"rb{month}.SF"} for month in months]
        return updater.classify_term_structure(contracts, "leftSymbol", self.histories, self.asof)

    def test_displayed_january_may_october_ignores_hidden_liquid_november(self):
        result = self.classify(["2701", "2705", "2710"])
        self.assertEqual(result["state"], "Contango")
        self.assertEqual([point["price"] for point in result["curve"]], [3037, 3050, 3081])
        self.assertEqual(result["contractCount"], 3)
        self.assertEqual(result["scope"], "displayed_contracts")

    def test_same_underlying_can_have_different_displayed_scopes(self):
        self.assertEqual(self.classify(["2701", "2705"])["state"], "Contango")
        self.assertEqual(self.classify(["2611", "2705"])["state"], "Back")

    def test_displayed_zero_volume_months_are_kept(self):
        result = self.classify(["2701", "2705", "2710"])
        self.assertEqual([point["expiry"] for point in result["curve"]], ["2701", "2705", "2710"])

    def test_mixed_and_flat_curves_are_not_reduced_to_endpoint_sign(self):
        for prices, expected in [([100, 120, 110], "混合"), ([120, 100, 110], "混合"), ([100, 100, 100], "平坦"), ([100, 100, 110], "Contango")]:
            with self.subTest(prices=prices):
                for month, price in zip(["2701", "2705", "2710"], prices):
                    self.histories[f"rb{month}.SF"].loc[self.asof, "close"] = price
                self.assertEqual(self.classify(["2701", "2705", "2710"])["state"], expected)

    def test_missing_displayed_quote_and_duplicate_months_fail(self):
        del self.histories["rb2705.SF"]
        with self.assertRaises(RuntimeError):
            self.classify(["2701", "2705", "2710"])
        with self.assertRaises(RuntimeError):
            self.classify(["2701", "2701"])

    def test_fewer_than_two_displayed_months_has_no_classification(self):
        self.assertIsNone(self.classify([]))
        self.assertIsNone(self.classify(["2701"]))


if __name__ == "__main__":
    unittest.main()
