"""Committed writes and seeded point SQL through public server client APIs.

Each read sample contains 100 requests; its median is a sample latency, not an
individual request percentile. Connections and all validation are outside timing.
"""
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import time

CASES = ("insert-commit", "batch-insert-commit", "random-get-hit",
         "random-get-miss", "random-update-commit", "random-delete-commit")


class Client:
    def __init__(self, engine):
        self.engine = engine
        if engine == "alopex-server":
            import alopex
            self.connection = alopex.connect(os.environ["ALOPEX_PERF_SERVER_URL"], keep_alive=True)
            assert isinstance(self.connection, alopex.RemoteDatabase), "Embedded fallback forbidden"
            self.mode = alopex.TxnMode.READ_WRITE
        elif engine == "postgresql":
            import psycopg
            from psycopg.rows import dict_row
            self.connection = psycopg.connect(os.environ["ALOPEX_PERF_POSTGRES_DSN"],
                                             autocommit=True, row_factory=dict_row,
                                             prepare_threshold=None)
        else:
            raise ValueError(f"Unknown engine: {engine}")

    def execute(self, sql, target=None):
        target = self.connection if target is None else target
        if self.engine == "alopex-server":
            return target.execute_sql(sql) or []
        cursor = target.execute(sql)
        return cursor.fetchall() if cursor.description else []

    def begin(self):
        if self.engine == "alopex-server":
            return self.connection.begin(self.mode)
        self.connection.execute("BEGIN")
        return self.connection

    def commit(self, transaction):
        transaction.commit()

    def rollback(self, transaction):
        transaction.rollback()

    def close(self):
        self.connection.close()


def _connect(engine):
    return Client(engine)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _assert_rows(actual, expected):
    assert actual == expected, "Mismatch in complete SQL result/state"
    for row, wanted in zip(actual, expected):
        assert set(row) == set(wanted), "Mismatch in SQL columns"
        assert all(type(row[key]) is type(value) for key, value in wanted.items()), "Mismatch in SQL types"


def _insert(rows):
    return "INSERT INTO bench_write (id, value) VALUES " + ",".join(
        f"({key}, '{value}')" for key, value in rows)


def _write(client, statements):
    transaction = client.begin()
    try:
        results = [client.execute(sql, transaction) for sql in statements]
        client.commit(transaction)
        return results
    except BaseException:
        try:
            client.rollback(transaction)
        except Exception:
            pass
        raise


def _plan(case, n, count):
    rng = random.Random(42)
    plans = []
    for index in range(count):
        if case in ("insert-commit", "batch-insert-commit"):
            size = 100 if case == "batch-insert-commit" else 1
            rows = [(n + index * size + offset, f"{n + index * size + offset:032x}") for offset in range(size)]
            plans.append(([_insert(rows)], rows))
        elif case in ("random-get-hit", "random-get-miss"):
            keys = [rng.randrange(n) + (n if case == "random-get-miss" else 0) for _ in range(100)]
            plans.append(([f"SELECT id, value FROM bench_write WHERE id = {key}" for key in keys], keys))
        else:
            key = rng.randrange(n)
            if case == "random-update-commit":
                value = f"{n + index:032x}"
                plans.append(([f"UPDATE bench_write SET value = '{value}' WHERE id = {key}"], [(key, value)]))
            else:
                plans.append(([f"DELETE FROM bench_write WHERE id = {key}"], [key]))
    return plans


def run(engine, case, work_dir, raw_path, n=10000, warmups=3, runs=21):
    if case not in CASES:
        raise ValueError(f"Unknown case: {case}")
    if n <= 0 or warmups < 0 or runs <= 0:
        raise ValueError("Positive rows/runs and nonnegative warmups required")
    plans = _plan(case, n, warmups + runs)
    read = case in ("random-get-hit", "random-get-miss")
    expected = {key: f"{key:032x}" for key in range(n)}
    statements = [sql for sqls, _ in plans for sql in sqls]
    if not read:
        statements = [statement for sqls, _ in plans for statement in ("BEGIN", *sqls, "COMMIT")]
    samples = []
    client = None
    # Exclusive creation protects partial evidence before any fixture mutation.
    with Path(raw_path).open("x") as raw:
        try:
            client = _connect(engine)
            client.execute("DROP TABLE IF EXISTS bench_write")
            client.execute("CREATE TABLE bench_write (id INTEGER PRIMARY KEY, value TEXT)")
            fixture = list(expected.items())
            _write(client, [_insert(fixture[start:start + 1000]) for start in range(0, n, 1000)])
            pending_restore = None
            for index, (sqls, payload) in enumerate(plans):
                if pending_restore is not None:
                    key, value = pending_restore
                    _write(client, [_insert([(key, value)])])
                    expected[key] = value
                    pending_restore = None
                started = time.perf_counter()
                result = [client.execute(sql) for sql in sqls] if read else _write(client, sqls)
                elapsed = time.perf_counter() - started
                if index >= warmups:
                    raw.write(json.dumps({"phase": "measure", "index": index - warmups, "seconds": elapsed}, allow_nan=False) + "\n")
                    raw.flush()
                    samples.append(elapsed)
                if read:
                    wanted = [[{"id": key, "value": expected[key]}] if key in expected else [] for key in payload]
                    assert len(result) == len(wanted), "Mismatch in request count"
                    for actual, rows in zip(result, wanted):
                        _assert_rows(actual, rows)
                else:
                    if case == "random-delete-commit":
                        key = payload[0]
                        pending_restore = (key, expected.pop(key))
                        _assert_rows(client.execute(f"SELECT id, value FROM bench_write WHERE id = {key}"), [])
                    else:
                        expected.update(payload)
                        keys = [key for key, _ in payload]
                        actual = client.execute("SELECT id, value FROM bench_write WHERE id IN (" + ",".join(map(str, keys)) + ") ORDER BY id")
                        _assert_rows(actual, [{"id": key, "value": expected[key]} for key in sorted(keys)])
            client.close()
            client = None
            client = _connect(engine)
            final = client.execute("SELECT id, value FROM bench_write ORDER BY id")
            _assert_rows(final, [{"id": key, "value": value} for key, value in sorted(expected.items())])
            return {"engine": engine, "case": case, "server_client": True,
                    "fixture_rows": n, "samples": runs, "warmups": warmups,
                    "operations_per_sample": 100 if case in ("batch-insert-commit", "random-get-hit", "random-get-miss") else 1,
                    "latency_p50_ms": statistics.median(samples) * 1000,
                    "result_sha256": _hash(final), "input_sha256": _hash(statements),
                    "final_rows": len(final), "validation": "every sample plus complete state after client reconnect"}
        finally:
            if client is not None:
                client.close()
