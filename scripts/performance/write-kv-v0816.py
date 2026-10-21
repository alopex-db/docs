"""Run committed SQL, native KV, or independently validated DataFrame cases."""
import argparse
import importlib.metadata
import importlib.util
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location("shared_sql", Path(__file__).with_name("server-sql-isolated-v0816.py"))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=("sql", "kv", "dataframe"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--engine")
    parser.add_argument("--case")
    args = parser.parse_args()
    os.environ.update({key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS", "TOKIO_WORKER_THREADS", "POLARS_MAX_THREADS")})
    os.sched_setaffinity(0, {1 if args.family == "sql" else 0})
    output, data = args.output.resolve(), args.data.resolve()
    if args.family == "sql":
        import write_kv_sql as module
        engines = ("alopex-server", "postgresql")
    elif args.family == "kv":
        import write_kv_native as module
        engines = ("alopex-kv", "lmdb")
    else:
        import dataframe_phases_v0816 as module
        engines = ("alopex", "polars")
    if args.case and args.case not in module.CASES:
        parser.error("Unknown case for selected family")
    if args.engine:
        if args.engine not in engines or not args.case:
            parser.error("Worker requires a valid engine and case")
        if args.family == "dataframe":
            value = module.run(args.engine, args.case, Path(os.environ["ALOPEX_PERF_RAW_PATH"]))
        else:
            value = module.run(args.engine, args.case, data, Path(os.environ["ALOPEX_PERF_RAW_PATH"]))
        print(json.dumps(value, allow_nan=False))
        return
    output.mkdir(parents=True, exist_ok=True)
    if (output / "environment.json").exists() or any(output.glob("case-*")):
        raise RuntimeError("Use a new run directory; do not overwrite partial evidence")
    cases = (args.case,) if args.case else module.CASES
    source_files = [Path(__file__), Path(module.__file__), Path(shared.__file__)]
    shared.save(output / "environment.json", {
        "schema": "alopex.performance-environment/v1", "family": args.family,
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu_model": next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")),
        "versions": {name: importlib.metadata.version(name) for name in ("alopex", "psycopg", "psycopg-binary", "lmdb", "polars", "polars-runtime-32")},
        "cpu_affinity": sorted(os.sched_getaffinity(0)), "server_cpu_affinity": [0] if args.family == "sql" else [],
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip(),
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
        "known_case_skips": {"drop-sequence": "Known defect #720, never part of this matrix"}})
    results = []
    for case in cases:
        for trial in range(3):
            order = engines if trial % 2 == 0 else tuple(reversed(engines))
            for engine in order:
                name = f"case-{case}-{engine}-trial{trial}"
                case_data = data / name
                os.environ["ALOPEX_PERF_RAW_PATH"] = str(output / f"{name}.raw.ndjson")
                command = [sys.executable, "-B", str(Path(__file__).resolve()), "--family", args.family,
                           "--output", str(output), "--data", str(case_data), "--engine", engine, "--case", case]
                status = shared.run_process(command, output, name, {"family": args.family, "case": case, "engine": engine, "trial": trial})
                row = dict(status)
                if row["exit_code"] == 0:
                    try:
                        value = json.loads((output / f"{name}.stdout.txt").read_text())
                        raw = [json.loads(line) for line in (output / f"{name}.raw.ndjson").read_text().splitlines()]
                        assert value["samples"] == len(raw) == 21 and value["warmups"] == 3
                        assert all(item["phase"] == "measure" and item["index"] == index and math.isfinite(item["seconds"]) and item["seconds"] > 0 for index, item in enumerate(raw))
                        assert value["result_sha256"] and value["input_sha256"]
                        row.update(value)
                        row.update(case=case, engine=engine)
                        shared.save(output / f"{name}.json", row)
                    except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
                        status.update(exit_code=65, validation_error=type(error).__name__)
                        row = dict(status)
                        shared.save(output / f"{name}.status.json", status)
                results.append(row)
                print(json.dumps(status), flush=True)
                if case_data.exists():
                    shutil.rmtree(case_data)
    summary = shared.relative(results, cases, engines)
    for cell in summary:
        inputs = {row.get("input_sha256") for row in results if row["case"] == cell["case"]}
        if len(inputs) != 1 or None in inputs:
            case = cell["case"]
            cell.clear()
            cell.update(case=case, comparison_status="failed", reason="input_digest_mismatch_or_missing")
    shared.save(output / "relative.json", {"schema": "alopex.performance-comparison/v1", "family": args.family,
                "subject": engines[0], "reference": engines[1], "cases": summary})


if __name__ == "__main__":
    main()
