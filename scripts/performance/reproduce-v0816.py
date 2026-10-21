"""Run the existing Alopex comparison cases in sequential, isolated processes."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def prepare(root, data):
    import numpy as np
    from hnsw_v0811_contract import (
        SEED, build_embeddings, exact_ground_truth, load_amazon_products,
    )
    from parity_v0811_measure import _write_csv, _write_parquet

    data.mkdir(parents=True, exist_ok=True)
    _write_csv(data / "rows.csv", 34250)
    _write_parquet(data / "rows.parquet", 34250)
    dataset = next((data / "amazon").rglob("*.csv"))
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == (
        "ec7ad773a70e654d65ee3757748fe99d614be24ad087330e437bcc84cda85291"
    )
    products = load_amazon_products(dataset)
    assert len(products) == 9171
    vectors, variance = build_embeddings(products)
    queries = vectors[np.random.default_rng(SEED).choice(len(vectors), size=200, replace=False)]
    truth, acceptable = exact_ground_truth(vectors, queries, 10)
    np.savez(data / "input.npz", vectors=vectors, queries=queries)
    write(data / "truth.json", {"truth": truth, "acceptable": acceptable, "variance": variance})
    write(data / "input-manifest.json", {
        "vectors_shape": list(vectors.shape), "queries_shape": list(queries.shape),
        "dtype": str(vectors.dtype),
        "vectors_sha256": hashlib.sha256(vectors.tobytes()).hexdigest(),
        "queries_sha256": hashlib.sha256(queries.tobytes()).hexdigest(),
    })


def hnsw_worker(engine_name, data, output):
    import numpy as np
    from hnsw_v0811_contract import (
        EF_SEARCH_VALUES, build_alopex, build_hnswlib, build_faiss_hnsw,
        measure_setting, peak_rss_bytes,
    )

    with np.load(data / "input.npz") as inputs:
        vectors, queries = inputs["vectors"], inputs["queries"]
    truth = json.loads((data / "truth.json").read_text())
    builders = {"alopex-hnsw": build_alopex, "hnswlib": build_hnswlib, "faiss-hnsw": build_faiss_hnsw}
    engine = builders[engine_name](vectors)
    try:
        assert engine.node_count == len(vectors)
        write(output.with_suffix(".build.json"), {
            "engine": engine_name, "node_count": engine.node_count,
            "build_time_seconds": engine.build_time_seconds,
            "index_size_bytes": engine.index_size_bytes,
            "note": "Build/persistence boundaries differ; these are diagnostic values, not speed ratios.",
        })
        runs = []
        for ef in EF_SEARCH_VALUES:
            runs.extend(measure_setting(
                engine, queries, truth["truth"], truth["acceptable"],
                ef_search=ef, min_queries=10000, run_count=1, dataset_size=len(vectors),
            ))
            write(output, {"engine": engine_name, "runs": runs, "peak_rss_bytes": peak_rss_bytes()})
    finally:
        engine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-root", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=["prepare", "tabular", "hnsw", "hnsw-worker"], required=True)
    parser.add_argument("--engine")
    args = parser.parse_args()
    root, data, output = args.harness_root.resolve(), args.data.resolve(), args.output.resolve()
    os.environ.update({key: "1" for key in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "POLARS_MAX_THREADS", "RAYON_NUM_THREADS",
    )})
    os.sched_setaffinity(0, {0})
    sys.path.insert(0, str(root / "scripts/performance"))
    if args.phase == "prepare":
        prepare(root, data)
        return
    if args.phase == "hnsw-worker":
        hnsw_worker(args.engine, data, output)
        return
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    write(output / "environment.json", {
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu_model": next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "versions": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "harness_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in data.iterdir() if p.is_file()},
    })
    cases = [
        ("polars-eager-api", ("alopex", "polars")),
        ("polars-csv-streaming", ("alopex", "polars")),
        ("polars-parquet-streaming", ("alopex", "polars")),
        ("sql-sqlite-curated", ("alopex", "sqlite")),
        ("sql-streaming", ("alopex", "datafusion")),
    ] if args.phase == "tabular" else [("hnsw", ("alopex-hnsw", "hnswlib", "faiss-hnsw"))]
    for case, engines in cases:
        for trial in range(3):
            order = engines[trial % len(engines):] + engines[:trial % len(engines)]
            for engine in order:
                name = f"{case}-{engine}-trial{trial}"
                result = output / f"{name}.json"
                status_path = result.with_suffix(".status.json")
                if status_path.exists():
                    if json.loads(status_path.read_text())["exit_code"]:
                        raise RuntimeError(f"Previous failure remains unresolved: {name}; use a new run directory")
                    continue
                if case == "hnsw":
                    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--harness-root", str(root), "--data", str(data), "--output", str(result), "--phase", "hnsw-worker", "--engine", engine]
                else:
                    fixture = data / ("rows.parquet" if "parquet" in case else "rows.csv")
                    command = [sys.executable, "-B", str(root / "scripts/performance/parity_v0811_measure.py"), "--worker", case, "--engine", engine, "--fixture", str(fixture), "--rows", "34250", "--warmups", "3", "--runs", "21"]
                env["ALOPEX_PERF_RAW_PATH"] = str(output / f"{name}.raw.ndjson")
                started = time.monotonic()
                with result.with_suffix(".stdout.txt").open("w") as stdout, result.with_suffix(".stderr.txt").open("w") as stderr:
                    completed = subprocess.run(command, env=env, cwd=root, stdout=stdout, stderr=stderr)
                status = {"case": case, "engine": engine, "trial": trial, "exit_code": completed.returncode, "elapsed_seconds": time.monotonic() - started}
                if not completed.returncode and case != "hnsw":
                    write(result, json.loads(result.with_suffix(".stdout.txt").read_text()))
                write(result.with_suffix(".status.json"), status)
                print(json.dumps(status), flush=True)
                size = sum(int(subprocess.check_output(["du", "-sb", str(path)], text=True).split()[0]) for path in (root.parents[3], data, Path(sys.prefix)))
                if size > 40_000_000_000:
                    raise RuntimeError("Owned measurement storage exceeded the 40 GB operating budget")
                if completed.returncode:
                    raise RuntimeError(f"Case failed: {name}; retained stderr and status")
                if case != "hnsw":
                    paired = [json.loads(path.read_text())["result_sha256"] for path in output.glob(f"{case}-*-trial{trial}.json") if not path.name.endswith(".status.json")]
                    if len(set(paired)) != 1:
                        write(output / f"{case}-trial{trial}.validation.json", {"status": "failed", "checksums": paired})
                        raise RuntimeError(f"Paired result checksum mismatch: {case} trial {trial}")


if __name__ == "__main__":
    main()
