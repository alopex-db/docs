import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VectorBenchmarkPublishingTests(unittest.TestCase):
    def test_workflow_imports_verified_json_and_markdown_idempotently(self):
        workflow = (
            ROOT / ".github/workflows/publish-vector-benchmarks.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("report/vector-benchmark-v*", workflow)
        self.assertIn("reports/vector-benchmarks/v${version}.json", workflow)
        self.assertIn("reports/vector-benchmarks/v${version}.md", workflow)
        self.assertIn('payload["markdown_sha256"]', workflow)
        self.assertIn("bash scripts/check-public-surface.sh", workflow)
        self.assertIn("git push origin main", workflow)

    def test_public_index_is_linked(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        index = ROOT / "reports/vector-benchmarks/README.md"
        self.assertIn("reports/vector-benchmarks/README.md", readme)
        self.assertTrue(index.is_file())


if __name__ == "__main__":
    unittest.main()
