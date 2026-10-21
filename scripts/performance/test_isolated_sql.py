import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("isolated", Path(__file__).with_name("server-sql-isolated-v0816.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IsolatedSqlTest(unittest.TestCase):
    def test_successful_remote_ddl_has_no_result_rows(self):
        import types
        from unittest.mock import patch

        class Remote:
            def execute_sql(self, sql):
                return None

            def close(self):
                pass

        alopex = types.SimpleNamespace(RemoteDatabase=Remote, connect=lambda *a, **k: Remote())
        with tempfile.TemporaryDirectory() as directory, patch.dict("sys.modules", {"alopex": alopex}), patch.dict("os.environ", {"ALOPEX_PERF_SERVER_URL": "http://localhost"}):
            value = module.measure(None, "alopex-server", "drop-sequence", Path(directory) / "raw.ndjson")
            self.assertEqual(value["samples"], 21)

    def test_full_result_checks_values_and_duplicates(self):
        rows = [{"id": 2, "value": 2.0}, {"id": 0, "value": 0.0}]
        module.validate("select-all", rows, 4)
        with self.assertRaises(AssertionError):
            module.validate("select-all", [{"id": 0, "value": 0.0}] * 2, 4)
        with self.assertRaises(AssertionError):
            module.validate("ordered", [{"id": 1, "value": 1.0}, {"id": 0, "value": 0.0}], 2)

    def test_failed_process_does_not_stop_next_case(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            failed = module.run_process([sys.executable, "-c", "raise SystemExit(7)"], path, "failed", {})
            passed = module.run_process([sys.executable, "-c", "print(123)"], path, "next", {})
            self.assertEqual(failed["exit_code"], 7)
            self.assertEqual(passed["exit_code"], 0)
            self.assertEqual((path / "next.stdout.txt").read_text().strip(), "123")

    def test_invalid_or_incomplete_cells_have_no_ratio(self):
        valid = [{"case": "aggregate", "engine": engine, "trial": trial, "exit_code": 0,
                  "latency_p50_ms": time, "result_sha256": "same"}
                 for trial in range(3) for engine, time in (("alopex-server", 2.0), ("postgresql", 1.0))]
        self.assertEqual(module.relative(valid, ["aggregate"])[0]["latency_ratio"], 2.0)
        for bad in (valid[:-1], [dict(x, exit_code=1) if i == 0 else x for i, x in enumerate(valid)],
                    [dict(x, result_sha256="different") if i == 0 else x for i, x in enumerate(valid)]):
            cell = module.relative(bad, ["aggregate"])[0]
            self.assertNotIn("latency_ratio", cell)
            self.assertEqual(cell["comparison_status"], "failed")
