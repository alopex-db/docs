"""Guard the injected server connection used by the existing SQL workload."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class ServerConnectionTest(unittest.TestCase):
    def test_partial_raw_attempt_is_preserved(self):
        spec = importlib.util.spec_from_file_location("server_comparison", Path(__file__).with_name("server-compare-v0816.py"))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            runner.require_new_run(output)
            raw = output / "measure-alopex-server-trial0.raw.ndjson"
            raw.write_text("partial-evidence\n")
            with self.assertRaisesRegex(RuntimeError, "partial and completed"):
                runner.require_new_run(output)
            self.assertEqual(raw.read_text(), "partial-evidence\n")

    def test_remote_factory_rejects_an_embedded_or_unknown_connection(self):
        script = Path(__file__).with_name("server-compare-v0816.py")
        spec = importlib.util.spec_from_file_location("server_comparison", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": "http://127.0.0.1:58080"}), patch("alopex.connect", return_value=object()):
            with self.assertRaisesRegex(RuntimeError, "must not use an embedded"):
                runner.connect("alopex-server")

    def test_sql_uses_supplied_connection_without_embedded_fallback(self):
        root = Path(os.environ["ALOPEX_HARNESS_ROOT"])
        sys.path.insert(0, str(root / "scripts/performance"))
        spec = importlib.util.spec_from_file_location("server_harness", root / "scripts/performance/parity_v0811_measure.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Connection:
            closed = False
            queries = []

            def execute_sql(self, sql):
                self.queries.append(sql)
                return [{"plan": "remote"}]

            def close(self):
                self.closed = True

        connection = Connection()
        # The existing sampler invokes real operations; fixture setup and state
        # validation are isolated here so this test owns only connection routing.
        with patch.object(module, "_populate_sql"), patch.object(module, "_prepare_sql_workload"), patch.object(module, "_validate_sql_state", return_value="same"), patch.object(module, "_sql_workload"):
            result = module._sql("alopex", "sql-postgresql-curated", 2, 0, 1, connection=connection)
        self.assertTrue(connection.closed)
        self.assertTrue(connection.queries)
        self.assertEqual(result["result_sha256"], "same")


if __name__ == "__main__":
    unittest.main()
