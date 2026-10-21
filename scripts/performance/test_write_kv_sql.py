"""Behavior checks use SQLite only as a fake client transport, never a reference."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import write_kv_sql as workload


class FakeClient:
    def __init__(self, path, state):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.state = state

    def execute(self, sql, target=None):
        if self.state.get("fail") and sql.startswith("UPDATE"):
            raise RuntimeError("controlled SQL failure")
        cursor = self.connection.execute(sql)
        result = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        if self.state.get("corrupt") and sql.startswith("SELECT") and result:
            result[0]["value"] = "wrong"
        return result

    def begin(self):
        self.connection.execute("BEGIN")
        return self.connection

    def commit(self, transaction):
        self.state["commits"] = self.state.get("commits", 0) + 1
        transaction.commit()

    def rollback(self, transaction):
        transaction.rollback()

    def close(self):
        self.connection.close()


class WorkloadTest(unittest.TestCase):
    def call(self, directory, case, state=None):
        state = {} if state is None else state
        path = Path(directory)
        with patch.object(workload, "_connect", side_effect=lambda engine: FakeClient(path / "data.db", state)):
            return workload.run("alopex-server", case, path, path / "raw.ndjson", n=7, warmups=1, runs=3)

    def test_every_case_checks_final_state_and_commits_writes(self):
        for case in workload.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                state = {}
                result = self.call(directory, case, state)
                self.assertEqual(result["samples"], 3)
                self.assertEqual(result["warmups"], 1)
                self.assertGreater(result["latency_p50_ms"], 0)
                self.assertEqual(len(result["result_sha256"]), 64)
                self.assertEqual(len(result["input_sha256"]), 64)
                self.assertEqual(result["operations_per_sample"], 100 if case in ("batch-insert-commit", "random-get-hit", "random-get-miss") else 1)
                raw = [json.loads(line) for line in (Path(directory) / "raw.ndjson").read_text().splitlines()]
                self.assertEqual([row["index"] for row in raw], [0, 1, 2])
                self.assertTrue(all(row["phase"] == "measure" for row in raw))
                # Three delete restores are also committed outside timing.
                expected = 1 if "get" in case else (8 if case == "random-delete-commit" else 5)
                self.assertEqual(state["commits"], expected)

    def test_result_mismatch_fails_instead_of_producing_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, "Mismatch"):
                self.call(directory, "random-get-hit", {"corrupt": True})

    def test_sql_failure_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "controlled SQL failure"):
                self.call(directory, "random-update-commit", {"fail": True})

    def test_seed_and_input_are_same_for_independent_runs(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = self.call(first, "random-get-hit")
            b = self.call(second, "random-get-hit")
            self.assertEqual(a["input_sha256"], b["input_sha256"])
            self.assertEqual(a["result_sha256"], b["result_sha256"])


if __name__ == "__main__":
    unittest.main()
