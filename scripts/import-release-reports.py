#!/usr/bin/env python3
"""Pull immutable report pairs from the public engine repo using docs' own token.

Only data from a report-only commit is imported. Incoming code is never executed.
Run-specific records cannot be overwritten. A complete scenario result additionally
updates the version's canonical JSON/Markdown pair, ordered by producing run/attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

_spec = importlib.util.spec_from_file_location("publication_record", Path(__file__).with_name("publication_record.py"))
publication = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publication)
FAILURE_BRANCH = re.compile(r"^report/verify-release-failure-v([0-9]+\.[0-9]+\.[0-9]+|unknown)-([1-9][0-9]*)-([1-9][0-9]*)$")

BRANCH = re.compile(r"^report/verify-release-v(\d+\.\d+\.\d+)-(\d+)-(\d+)$")
MARKERS = {
    "success": "✅ 全ステップ成功",
    "failure": "❌ 失敗あり",
    "incomplete": "⚠️ 未完了",
}


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def read_run(run_id):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "alopex-release-report-ingestion",
    }
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/alopex-db/alopex/actions/runs/{run_id}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_source_run(repo, ref, payload):
    verifier = payload.get("verifier_commit")
    parent = git(repo, "rev-parse", f"{ref}^").decode().strip()
    if verifier in (None, "unknown"):
        return  # Historical availability reports did not carry verifier identity.
    if not re.fullmatch(r"[0-9a-f]{40}", verifier):
        raise ValueError("invalid verifier commit")
    if parent != verifier:
        # A data-only branch need not carry an unmerged verifier's workflow files.
        # The producing Actions run binds the report to the actual tested verifier.
        origin = read_run(payload["identity"]["run_id"])
        if (
            origin.get("head_sha") != verifier
            or origin.get("head_repository", {}).get("full_name") != "alopex-db/alopex"
        ):
            raise ValueError("report differs from its producing source run")


def validate(payload, markdown, version, run_id, attempt, allow_unresolved=False):
    if (
        payload.get("schema") != "alopex-release-verification/v2"
        or payload.get("version") != version
    ):
        raise ValueError("schema/version mismatch")
    identity = payload.get("identity", {})
    if (identity.get("run_id"), identity.get("run_attempt")) != (run_id, int(attempt)):
        raise ValueError("producing run/attempt mismatch")
    unresolved = (allow_unresolved and payload.get("outcome") in {"failure", "incomplete"}
                  and identity.get("commit") == "unresolved"
                  and identity.get("tag") in {"unresolved", f"alopex-py-v{version}"})
    if not unresolved and (identity.get("tag") != f"alopex-py-v{version}" or not re.fullmatch(
        r"[0-9a-f]{40}", identity.get("commit", "")
    )):
        raise ValueError("release source identity missing")
    if (
        identity.get("run_url")
        != f"https://github.com/alopex-db/alopex/actions/runs/{run_id}"
    ):
        raise ValueError("unexpected run URL")
    if not payload.get("started_at") or not payload.get("completed_at"):
        raise ValueError("incomplete timing")
    steps = payload.get("steps")
    if not isinstance(steps, list) or any(
        not isinstance(s, dict) or s.get("status") not in MARKERS for s in steps
    ):
        raise ValueError("invalid steps")
    status = (
        "failure"
        if any(s["status"] == "failure" for s in steps)
        else "incomplete"
        if not steps or any(s["status"] == "incomplete" for s in steps)
        else "success"
    )
    if payload.get("outcome") != status:
        raise ValueError("outcome inconsistent with scenarios")
    expected_stage = next(
        (s["name"] for s in steps if s["status"] == status and status != "success"),
        "workflow orchestration" if not steps else None,
    )
    if payload.get("failure_stage") != expected_stage:
        raise ValueError("failure stage inconsistent with scenarios")
    text = markdown.decode("utf-8")
    if (
        not text.startswith(f"# リリース確認レポート: v{version}\n")
        or f"> 総合結果: **{MARKERS[status]}**" not in text
    ):
        raise ValueError("Markdown outcome differs from JSON")
    names = [s.get("name") for s in steps]
    for index, step in enumerate(steps, 1):
        mark = {"success": "✅", "failure": "❌", "incomplete": "⚠️"}[step["status"]]
        if f"### {index}. {step['name']} {mark}\n" not in text:
            raise ValueError("Markdown omits a recorded scenario")
    if payload.get("suite") == "scenarios" and status == "success":
        if not re.fullmatch(r"[0-9a-f]{40}", payload.get("verifier_commit", "")):
            raise ValueError("full scenario verifier identity missing")
        required = {
            "verify-release-embedded ビルド",
            "公開版 alopex-embedded 実行時依存 smoke",
            "公開版 SQL transaction failure conformance",
            "mode-parity 検証 (verify.py)",
            "mode-parity デモ (demo.py)",
            "v0.7 機能デモ: demo_cluster.py",
            "v0.7 機能デモ: demo_routing.py",
            "v0.7 機能デモ: demo_dataframe_p3.py",
            f"v{version} Embedded API 全シナリオ",
            f"v{version} ベクトル検索 API (demo_vector_api.py)",
            f"v{version} 組み込み API サーフェス (demo_api_surfaces.py)",
            f"v{version} v0.8.11 SQL mutation contracts",
        }
        if len(names) != 17 or len(set(names)) != 17 or not required.issubset(names):
            raise ValueError("successful scenario report lacks the complete suite")
    return payload


def canonical_markdown(markdown):
    """Correct a legacy display label while preserving immutable raw evidence."""
    old = "| ソースビルド | なし(公開パッケージのみ使用) |".encode()
    new = "| Rust製品の導入 | crates.ioの公開crateをコンパイル（作業コピーの製品コードは使用しない） |".encode()
    parts = markdown.rsplit(old, 1)
    return new.join(parts) if len(parts) == 2 else markdown


def put_immutable(path, content):
    if path.is_symlink():
        raise ValueError(f"symlink report refused: {path}")
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f"immutable report collision: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def import_failure(repo, ref, match):
    version, run_id, attempt = match.groups()
    stem = f"reports/release-verification/v{version}/run-{run_id}-{attempt}-publication-failure"

    def read(path):
        size = int(git(repo, "cat-file", "-s", f"{ref}:{path}"))
        mode = git(repo, "ls-tree", ref, "--", path).decode().split()[0]
        if size > publication.MAX_BYTES or mode != "100644":
            raise ValueError("invalid publication blob size/mode")
        return git(repo, "show", f"{ref}:{path}")

    record = json.loads(read(stem + ".json"))
    publication.validate(record)
    if (record["version"], record["run_id"], record["publication_attempt"]) != (version, run_id, int(attempt)):
        raise ValueError("publication branch identity mismatch")
    paths = {stem + "." + ext for ext in ("json", "md")}
    original = publication.original_stem(record)
    if original:
        paths.update(original + "." + ext for ext in ("json", "md"))
    changed = set(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", ref).decode().splitlines())
    if changed != paths:
        raise ValueError("publication commit changes unrelated or missing paths")
    blobs = {path: read(path) for path in paths}
    publication.verify_bundle(record, blobs)
    validate_source_run(repo, ref, {
        "verifier_commit": record["publisher_commit"], "identity": {"run_id": run_id},
    })
    if original:
        payload = json.loads(blobs[original + ".json"])
        validate(payload, blobs[original + ".md"], version, run_id,
                 record["verification"]["producing_attempt"], allow_unresolved=True)
        if payload["identity"]["commit"] != "unresolved":
            tag = git(repo, "rev-parse", f"refs/remotes/alopex/tags/alopex-py-v{version}^{{commit}}").decode().strip()
            if tag != payload["identity"]["commit"]:
                raise ValueError("original verification differs from public tag")
    # Check every collision first, including both original files. Failure evidence
    # never updates the canonical scenario pair or changes an original outcome.
    for path, data in blobs.items():
        target = repo / path
        if target.is_symlink() or (target.exists() and target.read_bytes() != data):
            raise ValueError(f"immutable publication collision: {path}")
    for path, data in blobs.items():
        put_immutable(repo / path, data)
    return [repo / path for path in sorted(paths)]


def import_ref(repo, ref):
    branch = ref.removeprefix("refs/remotes/alopex/")
    failure = FAILURE_BRANCH.fullmatch(branch)
    if failure:
        return import_failure(repo, ref, failure)
    match = BRANCH.fullmatch(branch)
    if not match:
        return []  # Legacy Markdown-only branches remain historical; never promote them.
    version, run_id, attempt = match.groups()
    stem = f"reports/release-verification/v{version}/run-{run_id}-{attempt}"
    paths = {f"{stem}.{ext}" for ext in ("md", "json")}
    changed = set(
        git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", ref)
        .decode()
        .splitlines()
    )
    # Pre-pair publishers left Markdown-only branches behind. Retain their
    # historical bytes, but never promote them to the canonical scenario pair.
    if changed == {f"{stem}.md"}:
        markdown = git(repo, "show", f"{ref}:{stem}.md")
        text = markdown.decode("utf-8")
        if not text.startswith(f"# リリース確認レポート: v{version}\n") or not any(
            f"> 総合結果: **{marker}**" in text for marker in MARKERS.values()
        ):
            raise ValueError("invalid legacy report header/outcome")
        target = repo / f"{stem}.md"
        put_immutable(target, markdown)
        return [target]
    if changed != paths:
        raise ValueError(f"report commit changes unrelated paths: {branch}")
    blobs = {ext: git(repo, "show", f"{ref}:{stem}.{ext}") for ext in ("md", "json")}
    payload = validate(json.loads(blobs["json"]), blobs["md"], version, run_id, attempt)
    # Resolve the immutable public Python tag without executing any incoming code.
    tag = (
        git(
            repo,
            "rev-parse",
            f"refs/remotes/alopex/tags/alopex-py-v{version}^{{commit}}",
        )
        .decode()
        .strip()
    )
    if tag != payload["identity"]["commit"]:
        raise ValueError("report source differs from peeled public tag")
    validate_source_run(repo, ref, payload)
    # Validate collisions before writing either half of the immutable pair.
    for ext, blob in blobs.items():
        target = repo / f"{stem}.{ext}"
        if target.is_symlink() or (target.exists() and target.read_bytes() != blob):
            raise ValueError(f"immutable report collision: {target}")
    written = []
    for ext, blob in blobs.items():
        target = repo / f"{stem}.{ext}"
        put_immutable(target, blob)
        written.append(target)
    if payload.get("suite") == "scenarios":
        canonical = repo / f"reports/release-verification/v{version}"
        prior_path = Path(str(canonical) + ".json")
        prior = json.loads(prior_path.read_text()) if prior_path.exists() else None
        rank = (int(run_id), int(attempt))
        prior_rank = (
            (-1, -1)
            if not prior
            else (int(prior["identity"]["run_id"]), prior["identity"]["run_attempt"])
        )
        if rank >= prior_rank:
            for ext, blob in blobs.items():
                target = Path(str(canonical) + "." + ext)
                if ext == "md":
                    blob = canonical_markdown(blob)
                if target.is_symlink():
                    raise ValueError("canonical symlink refused")
                target.write_bytes(blob)
                written.append(target)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--version", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.version and not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("version must be X.Y.Z")
    pattern = f"v{args.version}-*" if args.version else "v*"
    refs = (
        git(
            args.repo,
            "for-each-ref",
            "--format=%(refname)",
            f"refs/remotes/alopex/report/verify-release-{pattern}",
            f"refs/remotes/alopex/report/verify-release-failure-{pattern}",
        )
        .decode()
        .splitlines()
    )
    paths = set()
    for ref in refs:
        paths.update(import_ref(args.repo, ref))
    args.manifest.write_text(
        "".join(
            f"{p.relative_to(args.repo)}\t{hashlib.sha256(p.read_bytes()).hexdigest()}\n"
            for p in sorted(paths)
        )
    )
    print(f"validated {len(paths)} report files")


if __name__ == "__main__":
    main()
