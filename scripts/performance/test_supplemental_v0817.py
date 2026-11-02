"""Tiny receipt/child-lifecycle tests; no native imports, datasets or measurements."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import supplemental_v0817 as runner


def receipt(family="streaming", operation="alopex-original"):
    rows = 17125 if family == "streaming" else 34250
    return [dict(event="ready", rows=34250, operation=operation,
                 input_sha256="a"*64, result_sha256="b"*64),
            *[dict(event="sample", iteration=i, phase="warmup" if i < 3 else "measure",
                   total_ns=100+i, rows=rows) for i in range(24)],
            dict(event="complete", iterations=24, final_rows=rows, connection_closed=True,
                 result_sha256="b"*64, process_peak_rss_bytes=100)]


class ReceiptTests(unittest.TestCase):
    def validate(self, events, family="streaming"):
        with tempfile.TemporaryDirectory(prefix="alopex-supplemental-") as directory:
            path = Path(directory)/"raw.ndjson"
            path.write_text("\n".join(json.dumps(x) for x in events))
            return runner.validate_log(path, "alopex-original", family)

    def test_complete_receipt_retains_trial_median_and_linux_rss_units(self):
        self.assertEqual(self.validate(receipt())["median_ns"], 113)
        value = self.validate(receipt("sqlite"), "sqlite")
        self.assertEqual(value["process_peak_rss_bytes"], 102400)
        self.assertEqual(value["worker_complete"]["process_peak_rss_bytes"], 100)

    def test_missing_sample_duplicate_sample_and_incomplete_stream_are_rejected(self):
        for change in (lambda xs: xs.pop(5), lambda xs: xs.__setitem__(5, xs[4]),
                       lambda xs: xs[5].update(rows=1)):
            with self.subTest(change=change):
                events = receipt(); change(events)
                with self.assertRaises(RuntimeError): self.validate(events)

    def test_wrong_operation_or_final_state_is_rejected(self):
        for change in (lambda xs: xs[0].update(operation="datafusion-rows"),
                       lambda xs: xs[-1].update(result_sha256="c"*64),
                       lambda xs: xs[-1].update(connection_closed=False)):
            with self.subTest(change=change):
                events = receipt(); change(events)
                with self.assertRaises(RuntimeError): self.validate(events)

    def test_nan_zero_time_and_boundary_reordering_are_rejected(self):
        for change in (lambda xs: xs[3].update(total_ns=float("nan")),
                       lambda xs: xs[3].update(total_ns=0),
                       lambda xs: xs.insert(0, xs.pop())):
            with self.subTest(change=change):
                events = receipt(); change(events)
                with self.assertRaises(RuntimeError): self.validate(events)

    def test_complete_balanced_three_trial_schedule(self):
        for family in runner.FAMILIES:
            cells = runner.schedule(family)
            self.assertEqual(len(set(cells)), 12)
            for trial in range(3):
                selected = [x for x in cells if x[0] == trial]
                self.assertEqual(len(selected), 4)
                self.assertEqual(selected[0][2], "alopex" if trial != 1 else runner.FAMILIES[family][1][1])


@unittest.skipUnless(os.name == "posix", "Linux supervisor uses POSIX process groups")
class ChildTests(unittest.TestCase):
    def run_case(self, code, check=lambda: None, seconds=2):
        with tempfile.TemporaryDirectory(prefix="alopex-supplemental-") as directory:
            root = Path(directory)
            status = runner.run_child([sys.executable, "-c", code], os.environ.copy(), root,
                                      check, seconds, interval=0.01)
            self.assertEqual(status, json.loads((root/"status.json").read_text()))
            return status, (root/"raw.ndjson").read_text()

    def test_nonzero_exit_and_raw_output_are_preserved(self):
        status, raw = self.run_case("print('retained'); raise SystemExit(7)")
        self.assertEqual(status["exit_code"], 7)
        self.assertEqual(status["state"], "failed")
        self.assertEqual(raw, "retained\n")

    def test_timeout_stops_owned_process(self):
        status, _ = self.run_case("import time; time.sleep(10)", seconds=0.05)
        self.assertEqual(status["state"], "timeout")
        self.assertNotEqual(status["exit_code"], 0)

    def test_measurement_failure_prevents_launch_and_retains_failure(self):
        with tempfile.TemporaryDirectory(prefix="alopex-supplemental-") as directory, patch.object(runner.subprocess, "Popen") as launch:
            root = Path(directory)
            def fail(): raise OSError("inventory unavailable")
            with self.assertRaises(OSError):
                runner.run_child([sys.executable, "-c", "pass"], {}, root, fail, 1)
            launch.assert_not_called()
            self.assertEqual(json.loads((root/"status.json").read_text())["state"], "stopped")

    def test_excess_output_is_not_success(self):
        with patch.object(runner, "LOG_LIMIT", 10):
            status, _ = self.run_case("print('x'*11)")
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["reason"], "worker output limit")

    def test_live_measurement_error_stops_child_and_preserves_output(self):
        with tempfile.TemporaryDirectory(prefix="alopex-supplemental-") as directory:
            root=Path(directory)
            def check():
                if (root/"raw.ndjson").read_text().strip():
                    raise OSError("lost measurement")
            code="import os,time; print(os.getpid(),flush=True); time.sleep(10)"
            with self.assertRaises(OSError):
                runner.run_child([sys.executable,"-c",code],os.environ.copy(),root,check,5,
                                 interval=0.01,check_interval=0)
            pid=int((root/"raw.ndjson").read_text())
            with self.assertRaises(ProcessLookupError): os.kill(pid,0)
            self.assertEqual(json.loads((root/"status.json").read_text())["state"],"stopped")


class MatrixTests(unittest.TestCase):
    def test_ci_rejected_before_subject_or_storage_access(self):
        args = ["runner", "--manual", "--family", "streaming", "--harness-root", "/missing",
                "--harness-commit", "a"*40, "--plan", "/missing", "--output", "/missing",
                "--additional-bytes", "1024", "--case-seconds", "1"]
        with patch.object(sys, "argv", args), patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, {"CI":"true"}), patch.object(runner, "verify_subject") as verify:
            with self.assertRaisesRegex(RuntimeError, "forbidden in CI"): runner.main()
            verify.assert_not_called()

    def matrix(self, *, mismatch=False, child_failure=False, initial=100, noise=0.03):
        with tempfile.TemporaryDirectory(prefix="alopex-supplemental-") as directory:
            root = Path(directory); output = root/"output"; plan = root/"plan.json"
            runner.save(plan, {"schema":"alopex.performance-run-plan/v1", "family":"streaming",
                "harness_commit":"a"*40, "owner":"test", "comparison_subjects":["fixture"],
                "metric":"total_ns", "acceptance_rule":"test only", "cleanup":"owned work",
                "noise_fraction":noise, "subject_manifest_sha256":"b"*64})
            args = ["runner", "--manual", "--family", "streaming", "--harness-root", str(root),
                    "--harness-commit", "a"*40, "--plan", str(plan), "--output", str(output),
                    "--additional-bytes", "1024", "--case-seconds", "1"]
            calls=[]
            def child(command, env, cell, check, seconds):
                calls.append(cell.name)
                work=cell/"work"; work.mkdir(); (work/"one-byte").write_bytes(b"x")
                (cell/"raw.ndjson").write_text("preserved")
                return {"state":"failed" if child_failure and len(calls)==1 else "completed", "exit_code":7 if child_failure and len(calls)==1 else 0}
            def validate(path, operation, family):
                return {"input_sha256":"a"*64, "result_sha256":("c" if mismatch and operation.startswith("datafusion") else "b")*64, "median_ns":1}
            def git(root,*args): return "" if args[0]=="status" else "a"*40
            error=None
            with patch.object(sys,"argv",args), patch.object(sys,"platform","linux"), \
                 patch.dict(os.environ,{"ALOPEX_PERF_SUBJECT_MANIFEST":"fixture"},clear=True), \
                 patch.object(runner,"git",git), patch.object(runner,"sha",return_value="d"*64), \
                 patch.object(runner,"verify_subject",return_value={"manifest_sha256":"b"*64}), \
                 patch.object(os,"sched_setaffinity",create=True), patch.object(os,"sched_getaffinity",return_value={0},create=True), \
                 patch.object(runner,"load_storage",return_value=SimpleNamespace(check=lambda *a,**k:{"allocated_bytes":initial})), \
                 patch.object(runner,"run_child",child), patch.object(runner,"validate_log",validate):
                try: runner.main()
                except RuntimeError as caught: error=str(caught)
            self.assertFalse(list(output.glob("*/work")))
            statuses=[json.loads(p.read_text()) for p in output.glob("*/status.json")]
            return error,calls,statuses

    def test_all_cells_run_serially_and_owned_fixtures_are_removed(self):
        error,calls,statuses=self.matrix()
        self.assertIsNone(error); self.assertEqual(len(calls),12); self.assertEqual(len(statuses),12)

    def test_failed_cell_is_preserved_and_independent_cells_continue(self):
        error,calls,statuses=self.matrix(child_failure=True)
        self.assertIn("failed",error); self.assertEqual(len(calls),12)
        self.assertEqual(sum(s["state"]=="failed" for s in statuses),1)

    def test_cross_engine_digest_mismatch_fails_even_with_successful_children(self):
        error,calls,_=self.matrix(mismatch=True)
        self.assertIn("digests disagree",error); self.assertEqual(len(calls),12)

    def test_inclusive_host_budget_and_missing_numeric_criterion_prevent_work(self):
        for options in ({"initial":runner.STOP-1024},{"noise":None}):
            with self.subTest(options=options):
                error,calls,_=self.matrix(**options)
                self.assertIsNotNone(error); self.assertEqual(calls,[])


if __name__ == "__main__":
    unittest.main()
