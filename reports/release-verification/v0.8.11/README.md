# v0.8.11 release-verification evidence

This directory preserves every historical verification attempt for the
published `v0.8.11` release.  A failed attempt is evidence, not a file to be
replaced by a later retry.

| Attempt | Result | Evidence |
| --- | --- | --- |
| `20260908T171314+0900-attempt1` | Failed before image build: rootless Podman could not prepare its runtime directory. | [report](run-20260908T171314+0900-attempt1/report.md), [JSON](run-20260908T171314+0900-attempt1/report.json) |
| `20260908T171314+0900-attempt2` | Failed after image build: the rootless container could not write the verifier's bind-mounted build target. | [report](run-20260908T171314+0900-attempt2/report.md), [JSON](run-20260908T171314+0900-attempt2/report.json) |
| `20260909T035800+0900-attempt3` | Failed after image build: the temporary runner was launched outside its repository root. | [report](run-20260909T035800+0900-attempt3/report.md), [JSON](run-20260909T035800+0900-attempt3/report.json) |
| `20260909T040400+0900-attempt4` | Failed after three successful checks: the temporary runner did not contain `scripts/parity`. | [report](run-20260909T040400+0900-attempt4/report.md), [JSON](run-20260909T040400+0900-attempt4/report.json) |
| `20260909T044300+0900-attempt5` | Incomplete: embedded smoke and transaction conformance passed; mode-parity found missing gRPC proto input and v0.8.4 catalog compatibility errors. | [report](run-20260909T044300+0900-attempt5/report.md), [JSON](run-20260909T044300+0900-attempt5/report.json) |

The reports were generated from commit `c0ef1f7f77bf0ed966bc3b11dfbc239ed2806c53`
(`v0.8.11`) by `scripts/release/verify-release/run.sh`.
