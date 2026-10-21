import tempfile
from pathlib import Path
import unittest
import write_kv_native as module


class NativeKvTest(unittest.TestCase):
    def test_existing_key_and_value_contract(self):
        self.assertEqual(module.key_for(1), b"k:" + (1).to_bytes(8, "big"))
        self.assertEqual(len(module.value_for(1)), 32)

    def test_real_adapters_keep_identical_durable_results(self):
        for case in module.CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                results = [module.run(engine, case, root / engine, root / (engine + ".raw"), n=20, warmups=1, runs=2)
                           for engine in ("alopex-kv", "lmdb")]
                self.assertEqual(results[0]["result_sha256"], results[1]["result_sha256"])
                self.assertEqual(results[0]["input_sha256"], results[1]["input_sha256"])
                self.assertEqual(results[0]["samples"], 2)
                self.assertEqual(len((root / "alopex-kv.raw").read_text().splitlines()), 2)
