import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import backfill_historical_contracts as backfill


class BackfillCalendarTests(unittest.TestCase):
    def test_zhengzhou_safe_decade_moves_instead_of_reusing_2020(self):
        self.assertEqual(backfill.addressable_start_year("OI00.ZF", datetime(2029, 12, 31)), 2020)
        self.assertEqual(backfill.addressable_start_year("OI00.ZF", datetime(2030, 1, 1)), 2030)
        self.assertEqual(backfill.addressable_start_year("y00.DF", datetime(2030, 1, 1)), 0)
        with patch.object(backfill.dashboard, "CONTRACTS", {"OI00.ZF": {}}):
            candidates, roots = backfill.make_candidates(2020, 2031, datetime(2030, 1, 1))
        self.assertEqual(len(candidates), 2 * 12)
        self.assertEqual(set(roots.values()), {"OI00.ZF"})

    def test_weighted_pairs_map_to_the_backfilled_concrete_root(self):
        frames = {
            "y2701.DF": pd.DataFrame({"close": [8000]}, index=pd.to_datetime(["2026-11-05"])),
            "m2701.DF": pd.DataFrame({"close": [3000]}, index=pd.to_datetime(["2026-11-05"])),
        }
        contracts = {"y00.DF": {}, "m00.DF": {}}
        pairs = [{"pair": "fixture", "left": "yJQ00.DF", "right": "mJQ00.DF"}]
        with patch.object(backfill.dashboard, "CONTRACTS", contracts), patch.object(backfill.dashboard, "PAIRS", pairs):
            _, coverage, future, invalid = backfill.validate_coverage(frames, {"y2701.DF": "y00.DF", "m2701.DF": "m00.DF"}, 2026, 2027, datetime(2027, 1, 4))
        self.assertEqual(coverage["fixture"]["commonContractCount"], 1)
        self.assertEqual(coverage["fixture"]["missingYears"], [])
        self.assertFalse(future)
        self.assertEqual(invalid, [])

    def test_empty_coverage_reports_missing_years_without_crashing(self):
        contracts = {"y00.DF": {}, "m00.DF": {}}
        pairs = [{"pair": "fixture", "left": "yJQ00.DF", "right": "mJQ00.DF"}]
        with patch.object(backfill.dashboard, "CONTRACTS", contracts), patch.object(backfill.dashboard, "PAIRS", pairs):
            _, coverage, _, _ = backfill.validate_coverage({}, {}, 2026, 2027, datetime(2027, 1, 4))
        self.assertEqual(coverage["fixture"]["missingYears"], [2026, 2027])


if __name__ == "__main__":
    unittest.main()
