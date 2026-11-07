#!/usr/bin/env python3
"""Verify report hashes and recompute latency decisions from public raw samples."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(actual, expected):
    require(type(actual) in (float, int) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15),
            "recomputed value differs")


def verify(root):
    manifest = json.loads((root / "manifest.json").read_text())
    require(manifest["schema"] == "alopex.public-native-sql-report/v1" and
            manifest["samples"] == 2520 and manifest["cells"] == 120 and
            manifest["performance_acceptance"] is False, "unexpected report scope")
    require(digest(root / "comparison.json") == manifest["comparison_sha256"], "comparison digest differs")
    comparison = json.loads((root / "comparison.json").read_text())
    require(comparison["schema"] == "alopex.native-sql-comparison/v1" and
            comparison["performance_acceptance"] is False, "unsupported performance claim")
    cases = ("aggregate", "ordered", "select-all", "insert-rollback", "insert-commit", "batch-insert-commit",
             "random-get-hit", "random-get-miss", "random-update-commit", "random-delete-commit")
    subjects = ("published", "before", "candidate", "postgresql")
    require(len(manifest["raw_files"]) == 10 and
            {row["path"] for row in manifest["raw_files"]} == {"raw/" + case + ".ndjson" for case in cases},
            "raw file inventory differs")
    require(len(comparison["cases"]) == 10 and {row["case"] for row in comparison["cases"]} == set(cases),
            "comparison cases differ")
    samples = {}
    for entry in manifest["raw_files"]:
        path = root / entry["path"]
        require(path.stat().st_size == entry["size"] and digest(path) == entry["sha256"], "raw bytes differ")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        require(len(rows) == entry["samples"] == 252, "raw sample count differs")
        case = path.stem
        for row in rows:
            coordinate = row["case"], row["subject"], row["trial"], row["sample"]
            require(row["case"] == case and row["subject"] in subjects and row["trial"] in range(3) and
                    row["sample"] in range(21) and coordinate not in samples and
                    type(row["seconds"]) in (int, float) and math.isfinite(row["seconds"]) and row["seconds"] > 0,
                    "invalid sample coordinate or value")
            samples[coordinate] = row["seconds"]
    require(len(samples) == 2520, "sample coverage differs")
    statuses = {}
    for case in comparison["cases"]:
        values = {subject: [statistics.median(samples[case["case"], subject, trial, index] for index in range(21))
                            for trial in range(3)] for subject in subjects}
        for subject in subjects:
            require(len(case["trials"][subject]) == 3, "trial summary coverage differs")
            for actual, expected in zip(case["trials"][subject], values[subject]): close(actual, expected)
        medians = {name: statistics.median(values[name]) for name in subjects}
        deviations = {name: statistics.median(abs(x - medians[name]) for x in values[name]) for name in subjects}
        for subject in ("before", "published"):
            result = case["comparisons"][subject]
            baseline, candidate = medians[subject], medians["candidate"]
            noise = 3 * max(deviations[subject], deviations["candidate"])
            ratio = candidate / baseline
            expected = "pending_noise" if noise > .05 * baseline else "regression" if ratio > 1.05 else "within_tolerance"
            require(result["status"] == expected and result["increase"] is (candidate > baseline), "decision differs")
            require(result["exceeds_regression_threshold"] is (ratio > 1.05), "regression flag differs")
            close(result["noise"], noise); close(result["latency_ratio"], ratio)
            improved = (expected != "pending_noise" and (baseline - candidate) / baseline >= .05 and
                        baseline - candidate > noise and all(c < b for b, c in zip(values[subject], values["candidate"])))
            require(result["improvement_proven"] is improved, "improvement claim differs")
        close(case["reference_latency_ratio"], medians["candidate"] / medians["postgresql"])
        statuses[case["case"]] = {key: case["comparisons"][key]["status"] for key in ("before", "published")}
    return dict(verified_samples=len(samples), case_status=statuses, performance_acceptance=False)


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent), indent=2))
