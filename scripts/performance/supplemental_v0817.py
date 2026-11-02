"""Serial, manual Linux supervision for the existing streaming/SQLite workers."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time

from subject_identity import verify_subject, worker_command

FAMILIES = {
    "streaming": ("sql_stream_profile.py", ("alopex", "datafusion"), ("original", "rows")),
    "sqlite": ("sqlite_composite_profile.py", ("alopex", "sqlite"), ("original", "checked")),
}
STOP = 40_000_000_000
LOG_LIMIT = 2_000_000


def require(value, message):
    if not value:
        raise RuntimeError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schedule(family):
    _, engines, lanes = FAMILIES[family]
    return [(trial, lane, engine) for trial in range(3) for lane in lanes
            for engine in (engines if trial % 2 == 0 else tuple(reversed(engines)))]


def validate_log(path, operation, family):
    require(path.stat().st_size <= LOG_LIMIT, "worker log too large")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    require(all(isinstance(x, dict) for x in events), "invalid worker event")
    ready = [x for x in events if x.get("event") == "ready"]
    complete = [x for x in events if x.get("event") == "complete"]
    samples = [x for x in events if x.get("event") == "sample"]
    require(len(ready) == len(complete) == 1, "missing/duplicate worker boundary")
    begin, end = ready[0], complete[0]
    require(begin.get("rows") == 34250 and begin.get("operation") == operation,
            "wrong fixture or operation")
    require(len(samples) == 24 and end.get("iterations") == 24, "incomplete sample count")
    require(events.index(begin) < events.index(samples[0]) and
            events.index(samples[-1]) < events.index(end), "worker boundary order mismatch")
    for index, sample in enumerate(samples):
        require(sample.get("iteration") == index and
                sample.get("phase") == ("warmup" if index < 3 else "measure"),
                "sample order or phase mismatch")
        value = sample.get("total_ns")
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                "invalid sample duration")
        if family == "streaming":
            require(sample.get("rows") == 17125, "incomplete stream consumption")
    require(end.get("connection_closed") is True, "connection not closed")
    require(end.get("final_rows") == (17125 if family == "streaming" else 34250),
            "wrong final row count")
    for key in ("input_sha256", "result_sha256"):
        value = begin.get(key)
        require(isinstance(value, str) and len(value) == 64 and
                all(c in "0123456789abcdef" for c in value), "invalid " + key)
    require(begin["result_sha256"] == end.get("result_sha256"), "final result changed")
    # The existing worker checks values/types/state. This only checks its receipt.
    peak = end.get("process_peak_rss_bytes")
    require(type(peak) is int and peak > 0, "missing peak RSS")
    return {"input_sha256": begin["input_sha256"], "result_sha256": begin["result_sha256"],
            "median_ns": statistics.median(x["total_ns"] for x in samples[3:]),
            "process_peak_rss_bytes": peak * 1024 if family == "sqlite" else peak,
            "rss_note": "SQLite worker emits Linux ru_maxrss in KiB under its historical bytes field; raw retained",
            "worker_ready": begin, "worker_complete": end}


def stop(child):
    # The child owns a fresh process group. Also stop descendants if its leader exited.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_child(command, env, directory, check, seconds, *, interval=1, check_interval=15):
    """Retain all outcomes; a resource/measurement failure stops the whole matrix."""
    started = time.monotonic()
    status = {"command": command, "state": "failed"}
    child = None
    with (directory / "raw.ndjson").open("x") as out, (directory / "stderr.txt").open("x") as err:
        try:
            check()  # No child if measurement is unavailable or the budget is exhausted.
            child = subprocess.Popen(command, env=env, stdout=out, stderr=err, start_new_session=True)
            status["pid"] = child.pid
            last_check = time.monotonic()
            while child.poll() is None:
                if time.monotonic() - started >= seconds:
                    status.update(state="timeout", reason="case deadline")
                    break
                if out.tell() > LOG_LIMIT or err.tell() > LOG_LIMIT:
                    status.update(state="failed", reason="worker output limit")
                    break
                if time.monotonic() - last_check >= check_interval:
                    check()
                    last_check = time.monotonic()
                try:
                    child.wait(timeout=interval)
                except subprocess.TimeoutExpired:
                    pass
            else:
                status.update(state="completed" if child.returncode == 0 else "failed")
            stop(child)
            status["exit_code"] = child.returncode
            if out.tell() > LOG_LIMIT or err.tell() > LOG_LIMIT:
                status.update(state="failed", reason="worker output limit")
            check()
        except BaseException as error:
            if child is not None:
                stop(child)
            status.update(state="stopped", reason=type(error).__name__ + ": " + str(error))
            raise
        finally:
            status["elapsed_seconds"] = time.monotonic() - started
            save(directory / "status.json", status)
    return status


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def load_storage(path):
    spec = importlib.util.spec_from_file_location("measurement_storage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manual", action="store_true", required=True)
    p.add_argument("--family", choices=FAMILIES, required=True)
    p.add_argument("--harness-root", type=Path, required=True)
    p.add_argument("--harness-commit", required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--additional-bytes", type=int, required=True)
    p.add_argument("--case-seconds", type=int, required=True)
    p.add_argument("--storage-root", action="append", default=[])
    args = p.parse_args()
    require(sys.platform == "linux" and not os.environ.get("CI") and
            not os.environ.get("GITHUB_ACTIONS"), "manual Linux execution only; forbidden in CI")
    require(os.environ.get("ALOPEX_PERF_SUBJECT_MANIFEST"), "explicit subject manifest required")
    require(not os.environ.get("ALOPEX_PERF_RAW_PATH"), "unset raw-path override for original workers")
    require(0 < args.additional_bytes < STOP and 0 < args.case_seconds <= 3600,
            "invalid declared resource bounds")
    require(all(Path(path).exists() for path in args.storage_root), "explicit storage root is unavailable")
    root = args.harness_root.resolve()
    require(len(args.harness_commit) == 40 and git(root, "rev-parse", "HEAD") == args.harness_commit,
            "wrong pinned harness commit")
    require(not git(root, "status", "--porcelain", "--untracked-files=no"), "dirty tracked harness")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    require(plan.get("schema") == "alopex.performance-run-plan/v1", "wrong run plan schema")
    require(plan.get("family") == args.family and plan.get("harness_commit") == args.harness_commit,
            "run plan family/source mismatch")
    for field in ("owner", "comparison_subjects", "metric", "acceptance_rule", "cleanup"):
        require(bool(plan.get(field)), "run plan missing " + field)
    noise = plan.get("noise_fraction")
    require(type(noise) in (int, float) and math.isfinite(noise) and 0 <= noise < 1,
            "predeclared numeric noise fraction required")
    subject = verify_subject()
    require(plan.get("subject_manifest_sha256") == subject.get("manifest_sha256"),
            "run plan subject mismatch")
    os.sched_setaffinity(0, {0})
    os.environ.update({k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                       "POLARS_MAX_THREADS", "RAYON_NUM_THREADS", "TOKIO_WORKER_THREADS")})
    output = args.output.resolve()
    require(not output.exists(), "use a new output directory; never overwrite partial evidence")
    storage_path = root / "scripts/compatibility/storage.py"
    storage = load_storage(storage_path)
    extra = [root, output, Path(__file__).resolve().parents[2], Path(sys.prefix), Path.home()/".rustup",
             Path.home()/".cache/pip", Path.home()/".cache/maturin", *args.storage_root]
    initial = storage.check(extra=extra)["allocated_bytes"]
    require(initial + args.additional_bytes < STOP, "declared growth does not fit below 40 GB")
    output.mkdir(parents=True)
    limit = initial + args.additional_bytes
    check = lambda: storage.check(output / "storage.jsonl", extra=extra, limit=limit)
    driver, engines, lanes = FAMILIES[args.family]
    identity = {"subject": subject, "plan": plan, "plan_sha256": sha(args.plan),
                "harness_commit": args.harness_commit, "harness_tree": git(root, "rev-parse", "HEAD^{tree}"),
                "runner_sha256": sha(Path(__file__)), "storage_sha256": sha(storage_path),
                "driver_sha256": sha(root / "scripts/performance" / driver),
                "host": platform.node(), "platform": platform.platform(),
                "cpu_affinity": sorted(os.sched_getaffinity(0)),
                "initial_allocated_bytes": initial, "additional_bytes": args.additional_bytes,
                "case_seconds": args.case_seconds, "maximum_cases": 12, "warmups": 3, "samples": 21,
                "trials": 3, "rows": 34250}
    save(output / "environment.json", identity)
    results = []
    for trial, lane, engine in schedule(args.family):
        operation = engine + "-" + lane
        directory = output / f"trial{trial}-{operation}"
        directory.mkdir()
        work = directory / "work"
        command = worker_command([sys.executable, "-B", str(root/"scripts/performance"/driver),
                                  "--manual", "--surface", "embedded", "--rows", "34250",
                                  "--operation", operation, "--work", str(work)])
        try:
            status = run_child(command, os.environ.copy(), directory, check, args.case_seconds)
            if status["state"] == "completed":
                try:
                    status.update(validate_log(directory / "raw.ndjson", operation, args.family))
                except (ValueError, KeyError, TypeError, RuntimeError) as error:
                    status.update(state="invalid", reason=str(error))
            status.update(trial=trial, lane=lane, engine=engine)
            results.append(status)
            save(directory / "status.json", status)
            save(output / "results.json", results)
        finally:
            if work.exists():
                shutil.rmtree(work)  # Only this case's owned fixture directory.
            check()
    # Match full input/result identities across engines AND all three trials, per lane.
    comparable = []
    for lane in lanes:
        cells = [x for x in results if x["lane"] == lane]
        valid = all(x["state"] == "completed" for x in cells)
        valid = valid and all(len({x[key] for x in cells}) == 1 for key in ("input_sha256", "result_sha256"))
        comparable.append(valid)
        save(output / (lane + "-comparison.json"), {
            "state": "comparable" if valid else "incomplete_or_invalid", "cells": cells,
            "note": "No automatic release acceptance; apply the predeclared plan across subjects."})
    require(all(x["state"] == "completed" for x in results), "matrix contains failed/invalid/timeout cells")
    require(all(comparable), "matrix input/result digests disagree")


if __name__ == "__main__":
    main()
