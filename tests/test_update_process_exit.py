import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts import update_xtdata as updater


class UpdateProcessExitTests(unittest.TestCase):
    def test_without_native_runtime_uses_normal_exit(self):
        with patch.dict(sys.modules):
            sys.modules.pop("xtquant.xtdatacenter", None)
            with self.assertRaises(SystemExit) as raised:
                updater.exit_after_update(2)
        self.assertEqual(raised.exception.code, 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows worker lifecycle")
    def test_worker_preserves_success_and_failure_codes_and_flushes_logs(self):
        for exit_code in (0, 1, 2):
            with self.subTest(exit_code=exit_code):
                worker = subprocess.run(
                    [sys.executable, "-c", "\n".join([
                        "import sys",
                        "from scripts.update_xtdata import exit_after_update",
                        "sys.modules['xtquant.xtdatacenter'] = object()",
                        "sys.stdout.write('buffered stdout')",
                        "sys.stderr.write('buffered stderr')",
                        f"exit_after_update({exit_code})",
                    ])],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(worker.returncode, exit_code)
                self.assertEqual(worker.stdout, "buffered stdout")
                self.assertEqual(worker.stderr, "buffered stderr")


if __name__ == "__main__":
    unittest.main()
