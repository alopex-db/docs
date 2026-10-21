"""Validate retained case outputs and derive relative values without rerunning tests."""
import argparse
import json
import math
from pathlib import Path
import statistics


def median(values):
    assert values and all(math.isfinite(value) and value > 0 for value in values)
    return statistics.median(values)


def render(root):
    def load(name):
        return json.loads((root / name).read_text())

    cases = [
        ("polars-eager-api", "polars", "latency_p50_ms"),
        ("polars-csv-streaming", "polars", "total_p50_ms"),
        ("polars-parquet-streaming", "polars", "total_p50_ms"),
        ("sql-sqlite-curated", "sqlite", "latency_p50_ms"),
        ("sql-postgresql-curated", "postgresql", "latency_p50_ms"),
        ("sql-streaming", "datafusion", "total_p50_ms"),
    ]
    tabular = []
    for case, reference, metric in cases:
        durations = {}
        hashes = set()
        for engine in ("alopex", reference):
            values = []
            for trial in range(3):
                name = f"{case}-{engine}-trial{trial}"
                assert load(f"{name}.status.json")["exit_code"] == 0
                value = load(f"{name}.json")
                hashes.add(value["result_sha256"])
                records = [json.loads(line) for line in (root / f"{name}.raw.ndjson").read_text().splitlines()]
                samples = [record for record in records if record["phase"] in ("samples", "streaming", "sql-streaming")]
                expected_count = 21 if case == "polars-eager-api" else 63 if case.startswith("polars-") else 42
                assert len(samples) == expected_count, (name, len(samples), expected_count)
                for sample in samples:
                    seconds = sample.get("seconds", sample.get("total_seconds"))
                    assert math.isfinite(seconds) and seconds > 0
                values.append(value[metric])
            durations[engine] = values
        assert len(hashes) == 1, (case, hashes)
        ratio = median(durations["alopex"]) / median(durations[reference])
        paired = [left / right for left, right in zip(durations["alopex"], durations[reference])]
        tabular.append({"case": case, "reference": reference, "metric": metric,
                        "latency_ratio": ratio, "throughput_ratio": 1 / ratio,
                        "paired_latency_ratio_range": [min(paired), max(paired)],
                        "result_sha256": hashes.pop()})
    hnsw = {}
    for engine in ("alopex-hnsw", "hnswlib", "faiss-hnsw"):
        by_ef = {}
        for trial in range(3):
            name = f"hnsw-{engine}-trial{trial}"
            assert load(f"{name}.status.json")["exit_code"] == 0
            values = load(f"{name}.json")["runs"]
            assert [value["ef_search"] for value in values] == [16, 32, 64, 128, 256]
            for value in values:
                assert value["query_count"] >= 10000 and value["duration_seconds"] >= 2
                assert 0 <= value["recall_at_10"] <= 1
                by_ef.setdefault(value["ef_search"], []).append(value)
        hnsw[engine] = {ef: {"latency_us": median([v["query_latency_p50_us"] for v in values]),
                                    "trial_latencies_us": [v["query_latency_p50_us"] for v in values],
                                    "qps": median([v["queries_per_second"] for v in values]),
                                    "minimum_recall": min(v["recall_at_10"] for v in values),
                                    "minimum_tie_aware_recall": min(v["tie_aware_recall_at_10"] for v in values)}
                       for ef, values in by_ef.items()}
    fixed = []
    matched = []
    for reference in ("hnswlib", "faiss-hnsw"):
        for ef in (16, 32, 64, 128, 256):
            subject, other = hnsw["alopex-hnsw"][ef], hnsw[reference][ef]
            paired = [left / right for left, right in zip(subject["trial_latencies_us"], other["trial_latencies_us"])]
            fixed.append({"reference": reference, "ef_search": ef,
                          "latency_ratio": subject["latency_us"] / other["latency_us"],
                          "paired_latency_ratio_range": [min(paired), max(paired)],
                          "throughput_ratio": subject["qps"] / other["qps"],
                          "subject_recall": subject["minimum_recall"], "reference_recall": other["minimum_recall"]})
        for threshold in (0.95, 0.99):
            points = {}
            for engine in ("alopex-hnsw", reference):
                eligible = [(ef, value) for ef, value in hnsw[engine].items() if value["minimum_recall"] >= threshold]
                assert eligible, (engine, threshold)
                points[engine] = max(eligible, key=lambda item: item[1]["qps"])
            se, subject = points["alopex-hnsw"]
            re, other = points[reference]
            matched.append({"reference": reference, "recall_threshold": threshold,
                            "subject_ef": se, "reference_ef": re,
                            "latency_ratio": subject["latency_us"] / other["latency_us"],
                            "throughput_ratio": subject["qps"] / other["qps"],
                            "subject_recall": subject["minimum_recall"], "reference_recall": other["minimum_recall"]})
    payload = {"schema": "alopex.relative-performance-report/v1", "run_id": "20261021",
               "tabular": tabular, "hnsw_fixed_ef": fixed, "hnsw_matched_recall": matched}
    (root / "relative.json").write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    render(parser.parse_args().root)
