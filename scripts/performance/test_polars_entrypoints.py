import tempfile
from pathlib import Path
import unittest

import polars_entrypoints_v0816 as subject


class EntrypointTests(unittest.TestCase):
    def test_public_entrypoints_do_not_fall_back_to_dataframe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            subject.fixtures(root, 17)
            for case in subject.PROBES:
                with self.subTest(case=case):
                    actual = subject.probe("alopex", case, root, 17)
                    reference = subject.probe("polars", case, root, 17)
                    self.assertEqual(actual["status"], "capability-gap")
                    self.assertEqual(reference["status"], "supported")
                    self.assertNotIn("latency_p50_ms", actual)

    def test_lazy_scan_computes_and_consumes_all_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            subject.fixtures(root, 17)
            for case in subject.CASES:
                digests = []
                for engine in ("alopex", "polars"):
                    with self.subTest(engine=engine, case=case):
                        if engine == "alopex" and case in ("parquet-collect", "parquet-batches"):
                            with self.assertRaisesRegex(Exception, "expected Utf8, got LargeUtf8"):
                                subject.measure(engine, case, root, root / f"{engine}-{case}.raw", 17, 1, 2)
                            continue
                        result = subject.measure(engine, case, root, root / f"{engine}-{case}.raw", 17, 1, 2)
                        self.assertEqual(result["samples"], 2)
                        self.assertEqual(result["output_rows"], 17)
                        self.assertGreater(result["latency_p50_ms"], 0)
                        digests.append(result["result_sha256"])
                self.assertEqual(len(set(digests)), 1)

    def test_full_result_validator_rejects_value_type_null_and_order_changes(self):
        expected = {"id": [1, None, 3], "flag": [True, False, True]}
        for actual in (
            {"id": [2, None, 3], "flag": [True, False, True]},
            {"id": [1, 0, 3], "flag": [True, False, True]},
            {"id": [1, None, 3], "flag": [1, False, True]},
            {"flag": [True, False, True], "id": [1, None, 3]},
            {"id": [3, None, 1], "flag": [True, False, True]},
        ):
            with self.assertRaises(AssertionError):
                subject.assert_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()
