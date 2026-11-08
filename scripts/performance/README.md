# Performance subject identity

These are manual measurement entrypoints. Ordinary CI must not run the load or
performance matrix. Keep the existing rows, keys, seeds, complete-result oracles,
durability, timer boundaries, three warmups, 21 samples and three trials. The
original Linux affinity/topology requirements remain in place.

## Select the actual subject

For a new comparison, set `ALOPEX_PERF_SUBJECT_MANIFEST` to an absolute JSON
path. Use a separate manifest/run directory for the published baseline, fixed
pre-change build and final candidate, even when two report the same version.
No candidate commit is hard-coded in these scripts.

The build/qualification owner must first produce an immutable build receipt
from the exact clean source and release-profile build, with artifact hashes:

```json
{
  "schema": "alopex.performance-build/v1",
  "version": "0.8.17",
  "source": {"commit": "<40 lowercase hex>", "tree": "<40 lowercase hex>", "profile": "release"},
  "python_wheel_sha256": "<64 lowercase hex>",
  "server_sha256": "<64 lowercase hex, for server cases>"
}
```

For a wheel-only build, use `alopex.performance-wheel-build/v1` with the same
version, source and wheel-hash fields. Preserve the original receipt from the
builder. Native Python and DataFrame cases accept this receipt; server cases
reject it, even if a server hash is added. They require the combined build
receipt and the running-server checks below.

The selection manifest points to that receipt and the artifacts. Paths may be
absolute or relative to the manifest directory:

```json
{
  "schema": "alopex.performance-subject/v1",
  "version": "0.8.17",
  "source": {"commit": "<same commit>", "tree": "<same tree>", "profile": "release"},
  "build_receipt": {"path": "build.json", "sha256": "<receipt digest>"},
  "python_wheel": {"path": "alopex-0.8.17-<wheel tags>.whl", "sha256": "<wheel digest>"},
  "server": {
    "binary": {"path": "alopex-server", "sha256": "<server digest>"},
    "pid": 123,
    "start_ticks": 456,
    "url": "http://127.0.0.1:8080"
  }
}
```

The `server` member is required only for server cases. `start_ticks` is Linux
`/proc/PID/stat` field 22. The selected server must own the IPv4 listening socket
at the exact `ALOPEX_PERF_SERVER_URL`, run the receipt's executable bytes, retain
that process start time, and have CPU affinity `[0]`. The client retains `[1]`.
The checker does not start a server, alter affinity, install packages or connect
to a different device. Native/DataFrame cases retain client affinity `[0]`.

Before fixtures or sample timers, the checker verifies the receipt hash,
source/version/profile agreement, wheel hash and metadata, installed version,
every package file against the wheel, and the actual Python import location.
A source checkout shadowing the installed package or an editable installation
cannot silently replace the selected wheel. The manifest digest is pinned in
the parent's environment and inherited by each worker, which rechecks the
identity before executing its existing workload command. Environment reports
retain the selected identity and the checker source digest.

This is **artifact identity checking, not independent build attestation**. A
manually written `source.commit` cannot prove what produced a binary. Retain
the source-bound build/qualification logs with the receipt; do not relabel an
arbitrary existing wheel with a desired commit. Actual release-profile builds,
host storage measurement, candidate freezing, package qualification and the
full measurement matrix are separate work and are not completed by this change.

Example after the build owner has prepared and checked the real manifest:

```sh
export ALOPEX_PERF_SUBJECT_MANIFEST=/absolute/run/subject.json
python -B scripts/performance/write-kv-v0816.py \
  --family kv --output /absolute/run/results --data /absolute/run/data
```

To choose another subject, start a fresh process/environment, or unset
`ALOPEX_PERF_SUBJECT_SHA256` before selecting its manifest. Never change a
manifest or installed package during a run. Preserve partial/failing outputs.
The build owner's per-host storage watchdog must cover artifacts, environments,
data and outputs throughout execution; the identity checker is not a storage
monitor.

Without a manifest, historical reproduction retains the exact `0.8.16` version
check and labels its evidence `historical-version-only`. This mode rejects
`0.8.17` and is insufficient for new final-candidate comparisons. Polars remains
pinned to `1.43.2`, LMDB to `2.0.0`, and existing PostgreSQL/reference checks are
unchanged. This does not silently include previously excluded capability cases;
explicitly run and accept the required added cases in the release matrix.

## v0.8.17 final comparison coverage

The release acceptance owner is Codex, tracked in
[engine #690](https://github.com/alopex-db/alopex/issues/690) and
[engine #712](https://github.com/alopex-db/alopex/issues/712). This inventory maps
their original and added cases to existing entrypoints. It is preparation, not
a completed measurement or authorization to bypass candidate acceptance.

Run each applicable row for the published 0.8.16 baseline, the fixed pre-change
source, and the final composed candidate, with the pinned reference on the same
host. Record exact source/tree, runner source and artifact digests separately:
a runner checkout is not the product being measured. Do not use one product's
source SHA as the baseline for unrelated improvements without checking the
owning issue's existing baseline evidence. Preserve distinct run directories.

| Coverage | Existing entrypoint and explicit selection | Fixed boundary |
| --- | --- | --- |
| Original server SQL, 4 cases | `server-sql-isolated-v0816.py --harness-root <pinned-harness> --output <new-run>`: `aggregate`, `ordered`, `select-all`, `insert-rollback` | 34,250 rows for reads; initial 1 row for INSERT; public client/server round trip, complete results and rollback |
| Added server SQL, 6 cases | `write-kv-v0816.py --family sql --data <owned-data> --output <new-run>`: `insert-commit`, `batch-insert-commit`, `random-get-hit`, `random-get-miss`, `random-update-commit`, `random-delete-commit` | Initial 10,000 rows; committed writes include begin through durable commit; reconnect and verify full state |
| Native KV, 8 cases | Same entrypoint with `--family kv`: `put-commit`, `sequential-batch-put`, `random-batch-put`, `random-get-hit`, `random-get-miss`, `random-overwrite-commit`, `random-delete-commit`, `range-scan` | 10,000 keys; 10-byte key / 32-byte value; public embedded API, retained sync policy, close/reopen and verify all values |
| DataFrame, 4 phases | Same entrypoint with `--family dataframe`: `construct`, `compute`, `convert`, `complete` | 34,250 rows, existing 12-expression oracle; construction, compute and Python conversion remain separate |
| Lazy file computations, 6 cases | `polars_entrypoints_v0816.py --case <case> --data <new-data> --output <new-run>` for **each** of `csv-collect`, `csv-batches`, `parquet-collect`, `parquet-batches`, `parquet-numeric-collect`, `parquet-numeric-batches` | 34,250 rows; scan, compute and full collect/batch consumption; verify values/types/NULL/order. Parquet string cases are excluded by default and must be selected explicitly |
| Original eager/CSV/Parquet/SQLite/SQL-streaming boundaries | `reproduce-v0816.py --phase tabular --harness-root <pinned-harness> --data <prepared-input> --output <new-run>` covers `polars-eager-api`, `polars-csv-streaming`, `polars-parquet-streaming`, `sql-sqlite-curated`, `sql-streaming` | Original 34,250-row cases; CSV/Parquet 8,192-row batches fully consumed; keep historical harness corrections and hashes |
| HNSW search | Same entrypoint with `--phase hnsw` | 9,171 × 128 float32, seed 42, 200 query vectors, cosine/top-10, M16 / efConstruction200, efSearch16/32/64/128/256; 3 trials, at least 10,000 queries **and** 2 seconds per point, independent recall oracle |
| SQL streaming, equal Python result representation | Engine `scripts/performance/sql_stream_profile.py`: `alopex-original`, `datafusion-original`, `alopex-rows`, `datafusion-rows` | 34,250 input rows / 17,125 result rows. Retain original full-consumption and equal typed-row lanes separately; first row versus first batch is not a comparable latency |
| SQLite composite, explicit constraint semantics | Engine `scripts/performance/sqlite_composite_profile.py`: `alopex-original`, `sqlite-original`, `alopex-checked`, `sqlite-checked` | 34,250 rows; keep original workload and checked/FK-enabled lane separate; full results, rollback state and actual negative constraint checks |

The engine driver paths in the last two rows are relative to a separately
pinned engine checkout. Their existing `run_*_profile.py` supervisors are
macOS diagnostics, not the Linux final-comparison supervisor. Use the manual
Linux supervisor described below for those rows. Do not reinterpret an old
macOS diagnostic as a Linux final-candidate result. Implementing supervision
does not establish that a real candidate comparison has run.

Keep the six Polars entrypoint probes (`module-select`, `series-constructor`,
`series-arithmetic`, `lazy-constructor`, `module-scan-csv`,
`module-scan-parquet`) as capability results. Missing entrypoints and failed
string computation are not successful performance measurements. The Polars
parent records these probes alongside its selected measurement case.

The separate `server-compare-v0816.py --preflight` checks the existing 20-row
PostgreSQL composite contract for #720/#742 before any composite timing. Record
its six functional checks and final rollback checksum. A historical
`drop-sequence` failure does not block independent SQL cases and does not become
a #712 speed result. The old embedded-versus-server ratio stays invalid.

Before any dispatch, retain a run plan with these fields filled from evidence:

- Accepted candidate SHA/tree and issue inclusion; published baseline and
  each applicable pre-change SHA/tree; exact wheel/server build receipts.
- Pinned docs and engine harness commits, any historical correction patch
  digests, dataset digests, reference versions and selected case IDs. Never
  apply an old correction patch blindly to a newer harness.
- One physical host identity, CPU/thread affinity, filesystem/cache state,
  sync settings, reused connections, TLS/auth and prepared-statement policy.
  Server cases retain server CPU 0 / client CPU 1; native cases use CPU 0.
- Primary metric and numerical noise/improvement criterion **before** seeing
  candidate measurements. Preserve any stricter issue-specific criterion.
  An unresolved criterion is an unready run plan, not permission to choose a
  favorable threshold afterward.
- Measured inclusive host storage, command/output paths, bounded additional
  storage and elapsed time, stop/cleanup owner and timing. Serialize workloads
  and builds; stop at 40 GB, never exceed 50 GB. The checker does not enforce
  these resource limits itself.

Except for the HNSW-specific sampling contract, retain 3 warmups, 21 samples and
3 trials. Publish the ratio of trial-median summaries with trial ranges and raw
samples; report time, throughput, memory and I/O separately. Capture server and
client resources separately, and exclude raw-report writes from product I/O.
Keep failed, timed-out, skipped and unmeasured cells visible. Preserve partial
outputs and continue independent cells in new directories under the same budget.

Retain #681/#682/#684's separate source-bound acceptance comparisons, including
the 100,000 × 384 HNSW diagnostic and transaction preparation/index/commit
boundaries. They do not replace the original search matrix above. Track the
observed +10.8% SQL overflow commit, +9.87% HNSW construction and +11.40% ordered
memory scan costs through final acceptance rather than omitting them from a
summary of improvements. #712's full reference-parity goal remains open when
only its v0.8.17 stage is accepted. A performance run never establishes RC
package qualification, publication verification or the release-to-main merge.

## Supplemental Linux supervision

`supplemental_v0817.py` runs the existing engine streaming or SQLite worker in
12 serial processes per family: two independent lanes, two engines, three
trials with alternating engine order. It preserves 34,250 rows and the workers'
3 warmups / 21 samples and oracles. It does not install/build products, start a
server, or execute profiling. Both workers and supervisor reject CI execution.

Prepare the subject manifest above and a separate JSON run plan. The plan must
have schema `alopex.performance-run-plan/v1`, `family` (`streaming` or `sqlite`),
the exact `harness_commit`, matching `subject_manifest_sha256`, `owner`,
`comparison_subjects`, `metric`, `acceptance_rule`, `cleanup`, and a finite
numeric `noise_fraction` in [0, 1). Fill these from the predeclared acceptance
plan; the runner requires them but does not decide release acceptance. Record
all applicable published/pre-change/candidate identities in comparison_subjects.

After source, artifacts, reference versions, numerical criteria and host budget
are established, the command shape is:

```sh
python -B scripts/performance/supplemental_v0817.py --manual \
  --family streaming --harness-root <clean-pinned-engine-checkout> \
  --harness-commit <full-commit> --plan <absolute-plan.json> \
  --output <new-absolute-run-directory> \
  --additional-bytes <bounded-growth-bytes> --case-seconds <bounded-seconds>
```

Use a separate plan/output for `--family sqlite`. Add `--storage-root` for each
nonstandard Alopex location on the same physical host. The supervisor reuses the
pinned engine's inclusive allocated-byte inventory, adding docs, the selected
Python environment, complete Rust toolchains, pip/maturin caches and output.
It requires declared growth to fit strictly below 40 GB, checks before/after
every worker and at 15-second intervals, and stops the process group on resource
or measurement failure. It also bounds each worker's elapsed time and output.
Independent functional failures/timeouts retain raw/status and permit the
remaining cells; a storage or inventory failure stops the whole run.

Each worker verifies the selected subject before executing the existing driver.
The supervisor pins CPU 0 and one thread, records source/artifact/plan identities,
checks complete sample receipts, and compares full input/result digests across
engines and trials within each lane. Existing workers enforce the value/type/
state oracles; receipt validation does not replace them. Only owned per-case
`work` directories are removed. Raw logs, status, summaries and inventory remain
available on failures, and existing output directories are rejected.

SQLite's historical worker emits Linux `ru_maxrss` in KiB under a bytes-labelled
field. The supervisor preserves that raw field and reports a separate normalized
byte count. Stream workers already normalize it. These are lifetime process RSS
values, not isolated operation allocation measurements. No comparison is accepted
solely because child exit codes are zero or the receipt checks pass.

## Tiny functional verification

```sh
cd scripts/performance
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest -v test_subject_identity
```

These tests use tiny fake wheel/native bytes and proc files. One Linux-only
case opens a local listening socket in the test process, checks its real proc
identity, and restores its affinity without sending requests. They check mismatch
rejection, worker failure recording, setup-before-timing behavior and supported
Python syntax without building Alopex, starting a server, or making a performance
claim. Ordinary CI runs only these identity contracts. Native adapter tests and
the qualified product server require the separate execution environment.

## Optional SQL operation resource observations

For the four isolated SQL cases and six committed/random SQL cases, set
`ALOPEX_PERF_SQL_RESOURCE_MANIFEST` to an absolute JSON file before invoking the
existing manual runner. The schema is `alopex.sql-resource-servers/v1`; its
`servers` object maps `alopex-server` and `postgresql` to integer `pid` and
`start_ticks` values for the owned server root processes. Obtain start ticks
from field 22 of `/proc/PID/stat`, not from wall-clock time. Keep this manifest
with the run plan and raw evidence. The observer checks Alopex against the
qualified live subject and checks that the PostgreSQL connection backend is
inside the declared server tree. Existing topology and artifact checks still
apply. The optional observer never starts or configures a server.

Each measured sample records `resources` before any raw-file write or result
validation. The client uses `getrusage` CPU seconds and input/output block
counters, plus process RSS and Linux I/O byte counters. The server keeps
per-process CPU seconds and Linux `read_bytes`, `write_bytes`, and
`cancelled_write_bytes`. These are distinct kernel accounting
units, not network bytes or interchangeable metrics. Client usage excludes
server-counter enumeration. Resource collection is outside the existing latency
timer, but adds inter-sample work: enable it consistently for every compared
subject/reference and record its source and manifest digests. Do not mix enabled
and disabled observations as if they had identical execution conditions.

Memory records are RSS boundary values and lifetime high-water marks. They are
not operation peaks; server RSS is not summed because processes can share pages.
Server snapshot windows bracket the client timer and may include background
activity. Server CPU measurements have the host tick resolution. The observer
checks the PID-namespace allocation counter across both snapshots and the
operation, rejecting any allocation, including short-lived processes absent
from both endpoints. Use an isolated PID namespace for these resource runs;
unrelated allocations in a shared namespace also invalidate the sample. This
guard does not reconstruct process events or qualify a changing process tree.

An unavailable counter, decreased counter, changed PID/executable/thread/child
membership, PID allocation, or detected reaped child fails
the resource cell. A failure after the SQL operation preserves its elapsed
sample and error in raw output before propagating; missing I/O is never zero.
Some WSL kernels do not expose `/proc/PID/io`: such a host cannot qualify these
I/O observations. The real-counter functional test reports a skip there; tiny
fixtures still test parsing, boundaries, identity changes and missing-counter
rejection. This skip is not resource acceptance. With no manifest the historical
runner remains available, but its output does not establish server resources.

Run the functional tests with `python3 -B -m unittest -v test_sql_resources
test_write_kv_sql test_isolated_sql` from this directory. They use tiny fixtures
and no benchmark or load. Full live Alopex/PostgreSQL resource validation remains
a separately bounded manual check before accepting resource results.
