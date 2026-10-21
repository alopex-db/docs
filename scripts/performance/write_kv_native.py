"""The existing LSM KV workloads through two durable public Python APIs."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import resource
import statistics
import time

CASES = ("put-commit", "sequential-batch-put", "random-batch-put", "random-get-hit",
         "random-get-miss", "random-overwrite-commit", "random-delete-commit", "range-scan")


def key_for(index):
    return b"k:" + index.to_bytes(8, "big")


def value_for(index):
    return index.to_bytes(8, "little") * 4


class Store:
    def __init__(self, engine, root):
        self.engine = engine
        root.mkdir(parents=True, exist_ok=True)
        if engine == "alopex-kv":
            import alopex
            assert importlib.metadata.version("alopex") == "0.8.16"
            self.db = alopex.Database.open(str(root / "store.alopex"))
            self.read_mode, self.write_mode = alopex.TxnMode.READ_ONLY, alopex.TxnMode.READ_WRITE
        elif engine == "lmdb":
            import lmdb
            assert lmdb.__version__ == "2.0.0"
            self.db = lmdb.open(str(root / "store"), map_size=1024**3,
                                sync=True, metasync=True, writemap=False, map_async=False)
        else:
            raise ValueError(engine)

    def begin(self, write=False):
        if self.engine == "alopex-kv":
            return self.db.begin(self.write_mode if write else self.read_mode)
        return self.db.begin(write=write, buffers=False)

    def abort(self, txn):
        txn.rollback() if self.engine == "alopex-kv" else txn.abort()

    def scan(self, txn, start, end):
        if self.engine == "alopex-kv":
            return list(txn.scan_range(start, end))
        result = []
        with txn.cursor() as cursor:
            if cursor.set_range(start):
                for key, value in cursor:
                    if key >= end:
                        break
                    result.append((key, value))
        return result

    def write(self, rows, delete=False):
        txn = self.begin(True)
        try:
            for key, value in rows:
                txn.delete(key) if delete else txn.put(key, value)
            txn.commit()
        except BaseException:
            try:
                self.abort(txn)
            except Exception:
                pass
            raise

    def sync(self):
        self.db.flush() if self.engine == "alopex-kv" else self.db.sync(True)

    def close(self):
        self.db.close()


def _hash(rows):
    return hashlib.sha256(b"".join(key + value for key, value in rows)).hexdigest()


def _plans(case, n, count):
    rng = random.Random(7 if case in ("random-get-hit", "random-get-miss", "range-scan") else 42)
    result = []
    for index in range(count):
        if case in ("put-commit", "sequential-batch-put", "random-batch-put"):
            size = 1 if case == "put-commit" else 100
            ids = list(range(n + index * size, n + (index + 1) * size))
            if case == "random-batch-put":
                rng.shuffle(ids)
            result.append([(key_for(key), value_for(key)) for key in ids])
        elif case in ("random-get-hit", "random-get-miss"):
            result.append([(key_for(rng.randrange(n) + (n if case == "random-get-miss" else 0)), b"") for _ in range(100)])
        elif case == "range-scan":
            start = rng.randrange(n - min(n, 1000) + 1)
            result.append([(key_for(start), key_for(start + min(n, 1000)))])
        else:
            key = rng.randrange(n)
            result.append([(key_for(key), value_for(n + index))])
    return result


def run(engine, case, work_dir, raw_path, n=10000, warmups=3, runs=21):
    if case not in CASES or n <= 0 or warmups < 0 or runs <= 0:
        raise ValueError("Invalid KV measurement case or dimensions")
    root, raw_path = Path(work_dir), Path(raw_path)
    if root.exists() or raw_path.exists():
        raise RuntimeError("Do not overwrite a previous KV database or raw run")
    expected = {key_for(i): value_for(i) for i in range(n)}
    plans = _plans(case, n, warmups + runs)
    samples = []
    store = None
    with raw_path.open("x") as raw:
        try:
            store = Store(engine, root)
            store.write(sorted(expected.items()))
            store.sync()
            store.close()
            store = Store(engine, root)
            pending_restore = None
            for index, rows in enumerate(plans):
                if pending_restore:
                    store.write([pending_restore])
                    expected[pending_restore[0]] = pending_restore[1]
                    pending_restore = None
                started = time.perf_counter()
                if case in ("random-get-hit", "random-get-miss"):
                    result = []
                    for key, _ in rows:
                        txn = store.begin()
                        try:
                            result.append(txn.get(key))
                        finally:
                            store.abort(txn)
                elif case == "range-scan":
                    txn = store.begin()
                    try:
                        result = store.scan(txn, *rows[0])
                    finally:
                        store.abort(txn)
                else:
                    store.write(rows, delete=case == "random-delete-commit")
                    result = None
                elapsed = time.perf_counter() - started
                if index >= warmups:
                    raw.write(json.dumps({"phase": "measure", "index": index - warmups, "seconds": elapsed}) + "\n")
                    raw.flush()
                    samples.append(elapsed)
                if case in ("random-get-hit", "random-get-miss"):
                    wanted = [expected.get(key) for key, _ in rows]
                    assert result == wanted and all(type(a) is type(b) for a, b in zip(result, wanted)), "KV get result/type mismatch"
                elif case == "range-scan":
                    start, end = rows[0]
                    assert result == [(key, value) for key, value in sorted(expected.items()) if start <= key < end], "KV range result/order mismatch"
                else:
                    if case == "random-delete-commit":
                        key = rows[0][0]
                        pending_restore = (key, expected.pop(key))
                    else:
                        expected.update(rows)
                    txn = store.begin()
                    try:
                        for key, _ in rows:
                            assert txn.get(key) == expected.get(key), "Committed KV write not visible"
                    finally:
                        store.abort(txn)
            store.close()
            store = Store(engine, root)
            txn = store.begin()
            try:
                final = store.scan(txn, b"k:", b"l:")
                assert final == sorted(expected.items()), "KV complete state changed after reopen"
                assert all(type(k) is bytes and type(v) is bytes for k, v in final), "KV result type mismatch"
            finally:
                store.abort(txn)
            files = [path for path in root.rglob("*") if path.is_file()]
            return {"engine": engine, "case": case, "server_client": False,
                    "fixture_rows": n, "key_bytes": 10, "value_bytes": 32,
                    "samples": runs, "warmups": warmups,
                    "operations_per_sample": (100 if case in ("sequential-batch-put", "random-batch-put", "random-get-hit", "random-get-miss") else min(n, 1000) if case == "range-scan" else 1),
                    "latency_p50_ms": statistics.median(samples) * 1000,
                    "result_sha256": _hash(final), "input_sha256": _hash([row for plan in plans for row in plan]),
                    "final_rows": len(final), "validation": "every sample and complete bytes/order after close/reopen",
                    "client_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                    "store_logical_bytes": sum(path.stat().st_size for path in files),
                    "store_allocated_bytes": sum(path.stat().st_blocks * 512 for path in files)}
        finally:
            if store is not None:
                store.close()
