"""Identity checks use tiny fake artifacts and proc files, never product builds."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import subject_identity as subject
import write_kv_native
import dataframe_phases_v0816


class SubjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / "site/alopex"
        self.package.mkdir(parents=True)
        self.files = {"__init__.py": b"# tiny fake package\n", "_alopex.so": b"fake native bytes"}
        self.wheel = self.root / "alopex-0.8.17.whl"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr("alopex-0.8.17.dist-info/METADATA", "Name: alopex\nVersion: 0.8.17\n")
            for name, data in self.files.items():
                archive.writestr("alopex/" + name, data)
                (self.package / name).write_bytes(data)
        source = {"commit": "a" * 40, "tree": "b" * 40, "profile": "release"}
        self.receipt = self.root / "build.json"
        self.receipt.write_text(json.dumps({"schema": "alopex.performance-build/v1", "version": "0.8.17",
                                            "source": source, "python_wheel_sha256": subject.digest(self.wheel)}))
        self.manifest = self.root / "subject.json"
        self.value = {"schema": "alopex.performance-subject/v1", "version": "0.8.17", "source": source,
                      "build_receipt": {"path": self.receipt.name, "sha256": subject.digest(self.receipt)},
                      "python_wheel": {"path": self.wheel.name, "sha256": subject.digest(self.wheel)}}
        self.save()
        subject._verify.cache_clear()
        self.addCleanup(subject._verify.cache_clear)
        env = patch.dict(os.environ, {subject.MANIFEST_ENV: str(self.manifest)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        dist = SimpleNamespace(version="0.8.17", locate_file=lambda name: self.root / "site" / name)
        for mock in (patch.object(subject.importlib.metadata, "distribution", return_value=dist),
                     patch.object(subject.importlib.util, "find_spec", return_value=SimpleNamespace(origin=str(self.package / "__init__.py")))):
            mock.start()
            self.addCleanup(mock.stop)

    def save(self):
        self.manifest.write_text(json.dumps(self.value))

    def test_accepts_source_receipt_wheel_and_installed_bytes(self):
        result = subject.verify_subject()
        self.assertEqual(result["version"], "0.8.17")
        self.assertEqual(result["source"], self.value["source"])
        self.assertEqual(result["installed"]["verified_files"], 2)
        self.assertEqual(os.environ[subject.DIGEST_ENV], subject.digest(self.manifest))

    def test_changed_manifest_is_rejected_even_after_cached_verification(self):
        subject.verify_subject()
        self.value["source"]["commit"] = "c" * 40
        self.save()
        with self.assertRaisesRegex(RuntimeError, "manifest changed"):
            subject.verify_subject()

    def wheel_only_receipt(self, **changes):
        receipt = json.loads(self.receipt.read_text())
        receipt.update(schema="alopex.performance-wheel-build/v1", **changes)
        self.receipt.write_text(json.dumps(receipt))
        self.value["build_receipt"]["sha256"] = subject.digest(self.receipt)
        self.save()

    def test_wheel_only_receipt_verifies_installed_package(self):
        self.wheel_only_receipt()
        result = subject.verify_subject()
        self.assertEqual(result["source"], self.value["source"])
        self.assertEqual(result["installed"]["verified_files"], 2)
        self.assertEqual(result["build_receipt_sha256"], subject.digest(self.receipt))

    def test_wheel_only_receipt_cannot_qualify_server_even_after_python_check(self):
        self.wheel_only_receipt(server_sha256="c" * 64)
        subject.verify_subject()
        with patch.object(subject, "_server") as server:
            with self.assertRaisesRegex(RuntimeError, "requires a server build receipt"):
                subject.verify_subject(require_server=True)
            server.assert_not_called()

    def test_wheel_only_receipt_still_rejects_wrong_source(self):
        self.wheel_only_receipt(source=dict(self.value["source"], commit="c" * 40))
        with self.assertRaisesRegex(RuntimeError, "receipt source/version mismatch"):
            subject.verify_subject()

    def test_wheel_only_receipt_still_rejects_wrong_wheel(self):
        self.wheel_only_receipt(python_wheel_sha256="c" * 64)
        with self.assertRaisesRegex(RuntimeError, "not identified by the build receipt"):
            subject.verify_subject()

    def test_wheel_only_receipt_still_rejects_changed_installed_bytes(self):
        self.wheel_only_receipt()
        (self.package / "_alopex.so").write_bytes(b"wrong installed extension")
        with self.assertRaisesRegex(RuntimeError, "Installed wheel file mismatch"):
            subject.verify_subject()

    def test_receipt_for_another_source_is_rejected(self):
        self.value["source"]["commit"] = "c" * 40
        self.save()
        with self.assertRaisesRegex(RuntimeError, "receipt source/version mismatch"):
            subject.verify_subject()

    def test_changed_wheel_is_rejected(self):
        self.wheel.write_bytes(b"different wheel")
        with self.assertRaisesRegex(RuntimeError, "Artifact digest mismatch"):
            subject.verify_subject()

    def test_changed_installed_native_is_rejected(self):
        (self.package / "_alopex.so").write_bytes(b"another native artifact")
        with self.assertRaisesRegex(RuntimeError, "Installed wheel file mismatch"):
            subject.verify_subject()

    def test_unrecorded_installed_module_is_rejected(self):
        (self.package / "extra.py").write_text("# unexpected")
        with self.assertRaisesRegex(RuntimeError, "inventory differs"):
            subject.verify_subject()

    def test_shadowed_python_module_is_rejected(self):
        with patch.object(subject.importlib.util, "find_spec", return_value=SimpleNamespace(origin="/other/alopex/__init__.py")):
            with self.assertRaisesRegex(RuntimeError, "shadowed"):
                subject.verify_subject()

    def test_wrong_distribution_version_is_rejected(self):
        with patch.object(subject.importlib.metadata, "distribution", return_value=SimpleNamespace(version="0.8.16")):
            with self.assertRaisesRegex(RuntimeError, "Expected alopex 0.8.17"):
                subject.verify_subject()

    def test_debug_build_is_rejected(self):
        self.value["source"]["profile"] = "test"
        self.save()
        with self.assertRaisesRegex(RuntimeError, "release build"):
            subject.verify_subject()

    def test_legacy_mode_does_not_accept_candidate_by_removing_version_check(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(subject.importlib.metadata, "version", return_value="0.8.17"):
            with self.assertRaisesRegex(RuntimeError, "supply a subject manifest"):
                subject.verify_subject()
        with patch.dict(os.environ, {}, clear=True), patch.object(subject.importlib.metadata, "version", return_value="0.8.16"):
            self.assertEqual(subject.verify_subject()["identity_status"], "historical-version-only")

    def test_invalid_identity_precedes_kv_fixture_and_raw_creation(self):
        self.wheel.write_bytes(b"bad")
        data, raw = self.root / "db", self.root / "raw"
        with self.assertRaises(RuntimeError):
            write_kv_native.run("alopex-kv", "put-commit", data, raw, n=1, warmups=0, runs=1)
        self.assertFalse(data.exists())
        self.assertFalse(raw.exists())

    def test_invalid_identity_precedes_dataframe_input_allocation(self):
        self.wheel.write_bytes(b"bad")
        with patch.object(dataframe_phases_v0816, "inputs") as inputs:
            with self.assertRaises(RuntimeError):
                dataframe_phases_v0816.run("alopex", "construct", self.root / "raw", rows=1, warmups=0, runs=1)
            inputs.assert_not_called()

    def test_reference_version_pin_is_unchanged(self):
        with patch.object(dataframe_phases_v0816.importlib.metadata, "version", return_value="1.43.1"):
            with self.assertRaisesRegex(RuntimeError, "Expected polars 1.43.2"):
                dataframe_phases_v0816.Operations("polars", 1)

    def test_worker_keeps_command_arguments_and_rechecks_subject(self):
        command = [sys.executable, "-B", "script with spaces.py", "--case", "aggregate"]
        wrapped = subject.worker_command(command, True)
        self.assertEqual(wrapped[3], "server")
        self.assertEqual(wrapped[4:], command)

    def test_worker_identity_failure_is_recorded_and_workload_does_not_run(self):
        subject.verify_subject()
        self.value["source"]["commit"] = "d" * 40
        self.save()
        spec = importlib.util.spec_from_file_location("isolated_identity_test", Path(__file__).with_name("server-sql-isolated-v0816.py"))
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        marker = self.root / "workload-was-run"
        command = [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", str(marker)]
        status = isolated.run_process(command, self.root, "invalid", {"engine": "alopex"})
        self.assertNotEqual(status["exit_code"], 0)
        self.assertFalse(marker.exists())
        self.assertIn("Subject manifest changed", (self.root / "invalid.stderr.txt").read_text())
        self.assertEqual(json.loads((self.root / "invalid.status.json").read_text())["exit_code"], status["exit_code"])

    def server_fixture(self):
        proc_root = self.root / "proc"
        proc = proc_root / "123"
        (proc / "fd").mkdir(parents=True)
        (proc / "net").mkdir()
        binary = self.root / "server"
        binary.write_bytes(b"server identity")
        (proc / "exe").symlink_to(binary)
        (proc / "fd/3").symlink_to("socket:[456]")
        (proc / "stat").write_text("123 (name with ) parens) " + " ".join(["S"] + ["0"] * 18 + ["999"]))
        (proc / "net/tcp").write_text("header\n 0: 0100007F:1F90 00000000:0000 0A 0 0 0 0 0 456\n")
        return proc_root, proc, binary, {"pid": 123, "start_ticks": 999, "url": "http://127.0.0.1:8080"}

    def test_server_requires_same_process_binary_listener_and_affinity(self):
        proc_root, proc, binary, record = self.server_fixture()
        with patch.object(subject.sys, "platform", "linux"), patch.object(subject.os, "sched_getaffinity", return_value={0}, create=True), patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
            self.assertEqual(subject._server(record, binary, proc_root)["pid"], 123)
            (proc / "fd/3").unlink()
            with self.assertRaisesRegex(RuntimeError, "Endpoint is not owned"):
                subject._server(record, binary, proc_root)

    def test_server_reused_pid_is_rejected(self):
        proc_root, _, binary, record = self.server_fixture()
        record["start_ticks"] = 998
        with patch.object(subject.sys, "platform", "linux"), patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
            with self.assertRaisesRegex(RuntimeError, "process was replaced"):
                subject._server(record, binary, proc_root)

    def test_server_wrong_binary_is_rejected(self):
        proc_root, proc, binary, record = self.server_fixture()
        other = self.root / "other-server"
        other.write_bytes(b"different server")
        (proc / "exe").unlink()
        (proc / "exe").symlink_to(other)
        with patch.object(subject.sys, "platform", "linux"), patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
            with self.assertRaisesRegex(RuntimeError, "executable mismatch"):
                subject._server(record, binary, proc_root)

    def test_server_wrong_affinity_is_rejected(self):
        proc_root, _, binary, record = self.server_fixture()
        with patch.object(subject.sys, "platform", "linux"), patch.object(subject.os, "sched_getaffinity", return_value={1}, create=True), patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
            with self.assertRaisesRegex(RuntimeError, "CPU affinity"):
                subject._server(record, binary, proc_root)

    def test_configured_server_affinity_replaces_historical_topology(self):
        proc_root, _, binary, record = self.server_fixture()
        allocation = {"server": [4, 6], "client": [9]}
        with patch.object(subject.sys, "platform", "linux"), patch.object(subject.os, "sched_getaffinity", return_value={4, 6}, create=True), patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
            self.assertEqual(subject._server(record, binary, proc_root, cpu=allocation)["cpu_affinity"], [4, 6])
            with self.assertRaisesRegex(RuntimeError, "CPU affinity"):
                subject._server(record, binary, proc_root, cpu={"server": [7], "client": [9]})

    def test_invalid_cpu_assignments_fail_closed(self):
        for allocation in ({"server": [], "client": [1]}, {"server": [2], "client": [2]},
                           {"server": [True], "client": [1]}, {"server": [-1], "client": [1]},
                           {"server": [2, 2], "client": [1]}, {"server": [2]}):
            with self.subTest(allocation=allocation), self.assertRaises(RuntimeError):
                subject.cpu_assignment({"cpu": allocation})
        self.assertEqual(subject.cpu_assignment({}), {"server": [0], "client": [1]})

    def test_missing_server_identity_is_rejected_for_server_cases(self):
        with self.assertRaises(KeyError):
            subject.verify_subject(require_server=True)

    @unittest.skipUnless(sys.platform == "linux", "Linux proc/affinity contract")
    def test_linux_listener_identity_uses_real_proc_files(self):
        affinity = os.sched_getaffinity(0)
        if 0 not in affinity:
            self.skipTest("CPU 0 unavailable; original benchmark topology cannot run here")
        try:
            os.sched_setaffinity(0, {0})
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                pid = os.getpid()
                record = {"pid": pid, "start_ticks": subject._start_ticks(Path("/proc") / str(pid)),
                          "url": f"http://127.0.0.1:{listener.getsockname()[1]}"}
                with patch.dict(os.environ, {"ALOPEX_PERF_SERVER_URL": record["url"]}):
                    result = subject._server(record, Path(sys.executable))
                self.assertEqual(result["pid"], pid)
        finally:
            os.sched_setaffinity(0, affinity)

    def test_drivers_remain_python311_syntax_compatible(self):
        for path in Path(__file__).parent.glob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(), feature_version=(3, 11))


if __name__ == "__main__":
    unittest.main()
