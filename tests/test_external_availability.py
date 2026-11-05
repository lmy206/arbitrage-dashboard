import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import update_xtdata as updater


class ExternalAvailabilityTests(unittest.TestCase):
    def setUp(self):
        updater.FUTURE_EXTERNAL_ROWS_DISCARDED = 0

    def test_next_trading_day_is_excluded_without_changing_valid_prices(self):
        frame = pd.DataFrame(
            {"close": [100.0, 110.0, 999.0], "volume": [10, 20, 30]},
            index=pd.to_datetime(["2026-09-11", "2026-09-14", "2026-09-15"]),
        )
        actual = updater.available_external_frame(frame, pd.Timestamp("2026-09-14 22:00:00"))
        pd.testing.assert_frame_equal(actual, frame.iloc[:2])
        self.assertEqual(updater.FUTURE_EXTERNAL_ROWS_DISCARDED, 1)
        self.assertEqual(len(frame), 3)

    def test_all_future_input_remains_empty_instead_of_becoming_a_fake_current_row(self):
        frame = pd.DataFrame({"close": [999.0]}, index=pd.to_datetime(["2026-09-15"]))
        actual = updater.available_external_frame(frame, pd.Timestamp("2026-09-14"))
        self.assertTrue(actual.empty)
        self.assertEqual(updater.FUTURE_EXTERNAL_ROWS_DISCARDED, 1)

    def test_empty_cache_is_accepted(self):
        actual = updater.available_external_frame(pd.DataFrame(columns=["close", "volume"]), pd.Timestamp("2026-09-14"))
        self.assertTrue(actual.empty)
        self.assertEqual(updater.FUTURE_EXTERNAL_ROWS_DISCARDED, 0)

    def test_failed_integrity_preserves_the_last_good_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "arbitrage.json"
            output.write_text("previous valid dashboard", encoding="utf-8")
            report = {"status": "warning"}
            with patch.object(updater, "OUTPUT_PATH", output):
                updater.persist_dashboard_snapshot({"rows": []}, report)
            self.assertTrue(report["lastGoodOutputPreserved"])
            self.assertEqual(output.read_text(encoding="utf-8"), "previous valid dashboard")

    def test_successful_integrity_persists_only_the_validated_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new" / "arbitrage.json"
            payload = {"dataDate": "2028-01-04", "rows": [{"current": "3.0000"}]}
            with patch.object(updater, "OUTPUT_PATH", output):
                updater.persist_dashboard_snapshot(payload, {"status": "ok"})
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
