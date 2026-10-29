import json
import subprocess
from pathlib import Path
import unittest

import test_import_release_reports as fixtures

receiver = fixtures.REPORTS
contract = receiver.publication


class PublicationReportsTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.ReportTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.root
        self.ref = "refs/remotes/alopex/report/verify-release-failure-v0.8.16-123-2"

    def publish(self, original=True, extra=False, mutate=None, version="0.8.16"):
        record = {"schema": contract.SCHEMA, "repository": "alopex-db/alopex", "version": version,
                  "run_id": "123", "publication_attempt": 2, "publisher_commit": self.case.base,
                  "outcome": "failure", "stage": "docs_ingestion", "source_artifact": "release-verification-123-1",
                  "verification": None}
        blobs = {}
        if original:
            originals = {"json": json.dumps(self.case.payload).encode(), "md": self.case.md.encode()}
            record["verification"] = {"producing_attempt": 1, "outcome": self.case.payload["outcome"],
                                      "sha256": {ext: contract.digest(data) for ext, data in originals.items()}}
            blobs.update({contract.original_stem(record) + "." + ext: data for ext, data in originals.items()})
        prefix = contract.stem(record)
        blobs[prefix + ".json"] = json.dumps(record).encode()
        blobs[prefix + ".md"] = contract.render(record)
        if mutate:
            mutate(record, blobs)
        for name, data in blobs.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if extra:
            (self.root / "README.md").write_text("unrelated")
        fixtures.git(self.root, "add", ".")
        fixtures.git(self.root, "commit", "-qm", "publication failure")
        fixtures.git(self.root, "update-ref", self.ref, "HEAD")
        fixtures.git(self.root, "reset", "--hard", self.case.base)
        return record, blobs

    def test_import_keeps_successful_original_and_failure_separate_on_retry(self):
        record, blobs = self.publish()
        for _ in range(2):
            paths = receiver.import_ref(self.root, self.ref)
            self.assertEqual(len(paths), 4)
            self.assertEqual({str(p.relative_to(self.root)): p.read_bytes() for p in paths}, blobs)
        self.assertEqual(json.loads((self.root / (contract.original_stem(record) + ".json")).read_text())["outcome"], "success")
        self.assertFalse((self.root / "reports/release-verification/v0.8.16.json").exists())

    def test_unavailable_original_preserves_only_publication_evidence(self):
        record, blobs = self.publish(original=False)
        paths = receiver.import_ref(self.root, self.ref)
        self.assertEqual(len(paths), 2)
        self.assertIsNone(record["verification"])

    def test_unknown_version_without_original_is_retained(self):
        self.ref = "refs/remotes/alopex/report/verify-release-failure-vunknown-123-2"
        record, blobs = self.publish(original=False, version="unknown")
        paths = receiver.import_ref(self.root, self.ref)
        self.assertEqual({str(p.relative_to(self.root)): p.read_bytes() for p in paths}, blobs)
        self.assertIsNone(record["verification"])

    def test_original_collision_prevents_all_new_writes(self):
        record, _ = self.publish()
        path = self.root / (contract.original_stem(record) + ".json")
        path.parent.mkdir(parents=True)
        path.write_text("older immutable bytes")
        with self.assertRaisesRegex(ValueError, "collision"):
            receiver.import_ref(self.root, self.ref)
        self.assertEqual(path.read_text(), "older immutable bytes")
        self.assertFalse((self.root / (contract.stem(record) + ".json")).exists())

    def test_original_tampering_is_rejected(self):
        self.publish(mutate=lambda record, blobs: blobs.update({contract.original_stem(record) + ".md": b"changed"}))
        with self.assertRaisesRegex(ValueError, "digest"):
            receiver.import_ref(self.root, self.ref)

    def test_unrelated_changes_are_rejected(self):
        self.publish(extra=True)
        with self.assertRaisesRegex(ValueError, "unrelated"):
            receiver.import_ref(self.root, self.ref)

    def test_branch_attempt_cannot_relabel_failure(self):
        self.publish()
        wrong = self.ref[:-1] + "3"
        fixtures.git(self.root, "update-ref", wrong, self.ref)
        with self.assertRaises(subprocess.CalledProcessError):
            receiver.import_ref(self.root, wrong)

    def test_full_scenario_original_does_not_promote_canonical_from_failure(self):
        self.case.full_scenarios()
        self.publish()
        receiver.import_ref(self.root, self.ref)
        self.assertFalse((self.root / "reports/release-verification/v0.8.16.json").exists())

    def test_unresolved_release_is_retained_without_claiming_tag_validation(self):
        self.case.payload.update(outcome="failure", failure_stage="install")
        self.case.payload["identity"].update(commit="unresolved", tag="unresolved")
        self.case.payload["steps"][0]["status"] = "failure"
        self.case.md = self.case.md.replace("✅ 全ステップ成功", "❌ 失敗あり").replace("install ✅", "install ❌")
        record, _ = self.publish()
        receiver.import_ref(self.root, self.ref)
        stored = json.loads((self.root / (contract.original_stem(record) + ".json")).read_text())
        self.assertEqual(stored["identity"]["commit"], "unresolved")


if __name__ == "__main__":
    unittest.main()
