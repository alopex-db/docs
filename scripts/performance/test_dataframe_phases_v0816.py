"""Tiny functional checks; timings from these tests are not performance evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dataframe_phases_v0816 as workload


class FakeResult:
    def __init__(self, columns):
        self.columns = columns

    def to_dict(self, as_series=False):
        return copy.deepcopy(self.columns)


class FakeOperations:
    def __init__(self, engine, rows):
        pass

    def frame(self, columns):
        return copy.deepcopy(columns)

    def compute(self, frame):
        return FakeResult(workload.oracle(frame)["result"])

    def snapshot(self, frame, result=None, converted=None):
        snapshot = workload.oracle(frame)
        if result is not None:
            snapshot["result"] = result.to_dict(as_series=False)
        if converted is not None:
            snapshot["result"] = converted
        return snapshot


class FunctionalTest(unittest.TestCase):
    def test_validation_snapshot_is_released_outside_next_sample_timer(self):
        timing = [False]
        destruction = []

        class Snapshot:
            def __del__(self):
                destruction.append(timing[0])

        class Operations(FakeOperations):
            def snapshot(self, *args, **kwargs):
                return Snapshot()

        def clock():
            timing[0] = not timing[0]
            return float(len(destruction) + int(timing[0]))

        with tempfile.TemporaryDirectory() as directory, patch.object(workload, "Operations", Operations), patch.object(workload, "assert_equal"), patch.object(workload.time, "perf_counter", side_effect=clock):
            workload.run("alopex", "construct", Path(directory) / "raw.ndjson", rows=4, warmups=0, runs=2)
        self.assertEqual(destruction, [False, False])

    def test_oracle_explodes_every_row_and_preserves_null_and_order(self):
        result = workload.oracle(workload.inputs(4))
        self.assertEqual(result["next_id"], {"next_id": [1, 2, 3, 4]})
        self.assertEqual(result["explode"]["id"], [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual(result["explode"]["items"], ["0", "1", "1", "2", "2", "3", "3", "4"])
        self.assertEqual(result["result"]["joined"], [None, "row-1!", "row-2!", "row-3!"])

    def test_type_and_unchecked_column_corruption_are_rejected(self):
        expected = workload.oracle(workload.inputs(4))
        actual = copy.deepcopy(expected)
        actual["result"]["eq"][0] = 1
        with self.assertRaisesRegex(AssertionError, "type mismatch"):
            workload.assert_equal(actual, expected)
        actual = copy.deepcopy(expected)
        actual["explode"]["items"][-1] = "corrupt"
        with self.assertRaisesRegex(AssertionError, "value mismatch"):
            workload.assert_equal(actual, expected)

    def test_fake_phases_flush_exact_sample_rows_and_preserve_existing_raw(self):
        for case in workload.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                raw = Path(directory) / "raw.ndjson"
                with patch.object(workload, "Operations", FakeOperations):
                    result = workload.run("alopex", case, raw, rows=4, warmups=1, runs=2)
                    lines = [json.loads(line) for line in raw.read_text().splitlines()]
                    self.assertEqual([line["index"] for line in lines], [0, 1])
                    self.assertEqual(result["samples"], 2)
                    original = raw.read_bytes()
                    with self.assertRaises(FileExistsError):
                        workload.run("alopex", case, raw, rows=4, warmups=0, runs=1)
                    self.assertEqual(raw.read_bytes(), original)

    def test_setup_and_validation_stay_outside_phase_timers(self):
        for case, wanted in {
            "construct": ["timer", "frame", "timer", "snapshot"],
            "compute": ["frame", "timer", "compute", "timer", "snapshot"],
            "convert": ["frame", "compute", "timer", "convert", "timer", "snapshot"],
            "complete": ["timer", "frame", "snapshot", "timer"],
        }.items():
            events = []

            class Result(FakeResult):
                def to_dict(self, as_series=False):
                    events.append("convert")
                    return super().to_dict(as_series=as_series)

            class Operations(FakeOperations):
                def frame(self, columns):
                    events.append("frame")
                    return super().frame(columns)

                def compute(self, frame):
                    events.append("compute")
                    return Result(workload.oracle(frame)["result"])

                def snapshot(self, frame, result=None, converted=None):
                    events.append("snapshot")
                    snapshot = workload.oracle(frame)
                    snapshot["result"] = converted if converted is not None else (result.columns if result else snapshot["result"])
                    return snapshot

            def clock():
                events.append("timer")
                return len(events)

            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                with patch.object(workload, "Operations", Operations), patch.object(workload.time, "perf_counter", side_effect=clock):
                    workload.run("alopex", case, Path(directory) / "raw.ndjson", rows=4, warmups=0, runs=1)
                self.assertEqual(events, wanted)

    def test_both_public_engines_match_all_four_phase_oracles(self):
        hashes = set()
        for engine in ("alopex", "polars"):
            for case in workload.CASES:
                with self.subTest(engine=engine, case=case), tempfile.TemporaryDirectory() as directory:
                    result = workload.run(engine, case, Path(directory) / "raw.ndjson", rows=4, warmups=0, runs=1)
                    hashes.add((result["input_sha256"], result["result_sha256"]))
        self.assertEqual(len(hashes), 1)


if __name__ == "__main__":
    unittest.main()
