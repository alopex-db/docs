import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "reports", Path(__file__).parents[1] / "import-release-reports.py"
)
REPORTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORTS)


def git(root, *args):
    return (
        subprocess.check_output(
            ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "test")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "commit", "-qm", "base", "--allow-empty")
        self.base = git(self.root, "rev-parse", "HEAD")
        git(
            self.root,
            "update-ref",
            "refs/remotes/alopex/tags/alopex-py-v0.8.16",
            self.base,
        )
        self.payload = {
            "schema": "alopex-release-verification/v2",
            "version": "0.8.16",
            "identity": {
                "commit": self.base,
                "tag": "alopex-py-v0.8.16",
                "run_id": "123",
                "run_attempt": 1,
                "run_url": "https://github.com/alopex-db/alopex/actions/runs/123",
            },
            "verifier_commit": self.base,
            "started_at": "2026-10-20T00:00:00Z",
            "completed_at": "2026-10-20T00:00:01Z",
            "outcome": "success",
            "failure_stage": None,
            "steps": [{"name": "install", "status": "success"}],
        }
        self.md = "# リリース確認レポート: v0.8.16\n\n> 総合結果: **✅ 全ステップ成功**\n\n### 1. install ✅\n"
        self.stem = "reports/release-verification/v0.8.16/run-123-1"
        self.ref = "refs/remotes/alopex/report/verify-release-v0.8.16-123-1"

    def publish(self, extra=False):
        for ext, data in [("md", self.md), ("json", json.dumps(self.payload))]:
            path = self.root / f"{self.stem}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        if extra:
            (self.root / "README.md").write_text("unrelated")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "report")
        git(self.root, "update-ref", self.ref, "HEAD")
        git(self.root, "reset", "--hard", self.base)

    def test_pull_pair_and_retry_preserves_exact_bytes(self):
        self.publish()
        paths = REPORTS.import_ref(self.root, self.ref)
        self.assertEqual(len(paths), 2)
        before = {p: p.read_bytes() for p in paths}
        REPORTS.import_ref(self.root, self.ref)
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        self.assertFalse(
            (self.root / "reports/release-verification/v0.8.16.md").exists()
        )

    def test_collision_does_not_overwrite_either_half(self):
        self.publish()
        path = self.root / f"{self.stem}.md"
        path.parent.mkdir(parents=True)
        path.write_text("retained old evidence")
        with self.assertRaisesRegex(ValueError, "collision"):
            REPORTS.import_ref(self.root, self.ref)
        self.assertEqual(path.read_text(), "retained old evidence")
        self.assertFalse((self.root / f"{self.stem}.json").exists())

    def test_rejects_outcome_mismatch(self):
        self.payload["outcome"] = "failure"
        self.publish()
        with self.assertRaisesRegex(ValueError, "outcome"):
            REPORTS.import_ref(self.root, self.ref)

    def test_rejects_unrelated_source_changes(self):
        self.publish(extra=True)
        with self.assertRaisesRegex(ValueError, "unrelated"):
            REPORTS.import_ref(self.root, self.ref)

    def test_rejects_wrong_source_tag(self):
        self.payload["identity"]["commit"] = "a" * 40
        self.publish()
        with self.assertRaisesRegex(ValueError, "peeled public tag"):
            REPORTS.import_ref(self.root, self.ref)

    def test_rejects_relabelled_smoke_as_full_suite(self):
        self.payload["suite"] = "scenarios"
        self.publish()
        with self.assertRaisesRegex(ValueError, "complete suite"):
            REPORTS.import_ref(self.root, self.ref)

    def test_incomplete_report_is_retained_as_incomplete(self):
        self.payload.update(outcome="incomplete", failure_stage="install")
        self.payload["steps"][0]["status"] = "incomplete"
        self.md = self.md.replace("✅ 全ステップ成功", "⚠️ 未完了").replace(
            "install ✅", "install ⚠️"
        )
        self.publish()
        REPORTS.import_ref(self.root, self.ref)
        stored = json.loads((self.root / f"{self.stem}.json").read_text())
        self.assertEqual(stored["outcome"], "incomplete")

    def full_scenarios(self):
        names = [
            "verify-release-embedded ビルド",
            "公開版 alopex-embedded 実行時依存 smoke",
            "公開版 SQL transaction failure conformance",
            "mode-parity 検証 (verify.py)",
            "mode-parity デモ (demo.py)",
            "v0.7 機能デモ: demo_cluster.py",
            "v0.7 機能デモ: demo_routing.py",
            "v0.7 機能デモ: demo_dataframe_p3.py",
            "v0.8.16 Embedded API 全シナリオ",
            "v0.8.16 ベクトル検索 API (demo_vector_api.py)",
            "v0.8.16 組み込み API サーフェス (demo_api_surfaces.py)",
            "v0.8.16 v0.8.11 SQL mutation contracts",
            "install",
            "aggregate",
            "scalar",
            "SQL",
            "v0.8.16 public vector scenario",
        ]
        self.payload["suite"] = "scenarios"
        self.payload["steps"] = [{"name": name, "status": "success"} for name in names]
        self.md = (
            "# リリース確認レポート: v0.8.16\n\n> 総合結果: **✅ 全ステップ成功**\n\n"
            + "".join(f"### {i}. {name} ✅\n" for i, name in enumerate(names, 1))
        )

    def test_full_scenarios_publish_canonical_and_immutable_pairs(self):
        self.full_scenarios()
        self.publish()
        paths = REPORTS.import_ref(self.root, self.ref)
        self.assertEqual(len(paths), 4)
        for ext in ["md", "json"]:
            self.assertEqual(
                (
                    self.root / f"reports/release-verification/v0.8.16.{ext}"
                ).read_bytes(),
                (self.root / f"{self.stem}.{ext}").read_bytes(),
            )

    def test_older_pending_run_cannot_replace_newer_canonical_report(self):
        self.full_scenarios()
        self.publish()
        prior = json.loads(json.dumps(self.payload))
        prior["identity"]["run_id"] = "456"
        canonical = self.root / "reports/release-verification/v0.8.16.json"
        canonical.parent.mkdir(parents=True)
        canonical.write_text(json.dumps(prior))
        markdown = canonical.parent / "v0.8.16.md"
        markdown.write_text("newer canonical")
        REPORTS.import_ref(self.root, self.ref)
        self.assertEqual(markdown.read_text(), "newer canonical")
        self.assertEqual(json.loads(canonical.read_text())["identity"]["run_id"], "456")


if __name__ == "__main__":
    unittest.main()
