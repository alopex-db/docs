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
