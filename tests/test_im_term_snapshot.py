"""IM source failures preserve the previous real dated snapshot without mutation."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("im_snapshot_test", Path(__file__).resolve().parents[1] / "scripts/im_term_snapshot.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImTermSnapshot(unittest.TestCase):
    def test_source_failure_retains_the_previous_real_date_and_prices(self):
        previous = {"id": "im", "queries": {"latest": {"rows": [{"date": "2026-11-05", "indexClose": 6650.138, "stale": False}]}}}
        before = copy.deepcopy(previous)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"IM_THRESHOLD_VAULT": folder}):
            result = module.load_im_term_snapshot(previous)
        self.assertEqual(previous, before)
        self.assertEqual(result["queries"]["latest"]["rows"][0]["date"], "2026-11-05")
        self.assertEqual(result["queries"]["latest"]["rows"][0]["indexClose"], 6650.138)
        self.assertTrue(result["queries"]["latest"]["rows"][0]["stale"])
        self.assertEqual(result["queries"]["latest"]["rows"][0]["lastRefreshStatus"], "xtdata_unavailable")

    def test_no_source_and_no_previous_snapshot_is_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"IM_THRESHOLD_VAULT": folder}):
            with self.assertRaisesRegex(RuntimeError, "no prior valid snapshot"):
                module.load_im_term_snapshot()
