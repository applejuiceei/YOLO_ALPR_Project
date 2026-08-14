from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_LIMIT_MIB = 95.0
ZERO_OID = "0" * 40


@dataclass(frozen=True)
class Blob:
    oid: str
    size: int
    path: str


def run_git(args: list[str], *, stdin: str | None = None) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        input=stdin.encode("utf-8") if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return completed.stdout


def staged_blobs() -> list[Blob]:
    names = run_git(["diff", "--cached", "--name-only", "--diff-filter=AM", "-z"])
    paths = [item.decode("utf-8", errors="surrogateescape") for item in names.split(b"\0") if item]
    blobs: list[Blob] = []
    for path in paths:
        oid = run_git(["rev-parse", f":{path}"]).decode("ascii").strip()
        size = int(run_git(["cat-file", "-s", oid]).decode("ascii").strip())
        blobs.append(Blob(oid=oid, size=size, path=path))
    return blobs


def revision_objects(revisions: Iterable[str]) -> dict[str, str]:
    revision_list = [revision for revision in revisions if revision]
    if not revision_list:
        return {}
    output = run_git(["rev-list", "--objects", *revision_list])
    objects: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.decode("utf-8", errors="surrogateescape")
        oid, separator, path = line.partition(" ")
        if oid and oid not in objects:
            objects[oid] = path if separator else "<history object>"
    return objects


def blobs_from_revisions(revisions: Iterable[str]) -> list[Blob]:
    objects = revision_objects(revisions)
    if not objects:
        return []
    request = "".join(f"{oid}\n" for oid in objects)
    output = run_git(
        ["cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        stdin=request,
    )
    blobs: list[Blob] = []
    for raw_line in output.splitlines():
        fields = raw_line.decode("ascii", errors="replace").split()
        if len(fields) != 3 or fields[1] != "blob":
            continue
        oid, _object_type, raw_size = fields
        blobs.append(Blob(oid=oid, size=int(raw_size), path=objects.get(oid, "<unknown>")))
    return blobs


def pre_push_revisions(lines: Iterable[str]) -> list[str]:
    revisions: list[str] = []
    for line in lines:
        fields = line.strip().split()
        if not fields:
            continue
        if len(fields) != 4:
            raise RuntimeError(f"unexpected pre-push input: {line.rstrip()!r}")
        _local_ref, local_oid, _remote_ref, remote_oid = fields
        if local_oid == ZERO_OID:
            continue
        revisions.append(local_oid if remote_oid == ZERO_OID else f"{remote_oid}..{local_oid}")
    return revisions


def format_mib(size: int) -> str:
    return f"{size / (1024 * 1024):.2f} MiB"


def check(blobs: Iterable[Blob], limit_mib: float) -> int:
    limit_bytes = int(limit_mib * 1024 * 1024)
    unique: dict[str, Blob] = {blob.oid: blob for blob in blobs}
    violations = sorted(
        (blob for blob in unique.values() if blob.size >= limit_bytes),
        key=lambda blob: blob.size,
        reverse=True,
    )
    if not violations:
        largest = max(unique.values(), key=lambda blob: blob.size, default=None)
        detail = f"; largest={format_mib(largest.size)} {largest.path}" if largest else ""
        print(f"Large-file guard passed: {len(unique)} blobs checked, limit={limit_mib:g} MiB{detail}")
        return 0

    print(
        f"ERROR: {len(violations)} Git blob(s) meet or exceed the {limit_mib:g} MiB limit:",
        file=sys.stderr,
    )
    for blob in violations:
        print(f"  {format_mib(blob.size):>12}  {blob.path}  ({blob.oid[:12]})", file=sys.stderr)
    print(
        "Remove the file from the commits being pushed and store it outside normal Git. "
        "Adding it to .gitignore after it was committed is not sufficient.",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reject Git blobs that are too large for this repository.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="Check added or modified staged blobs.")
    mode.add_argument("--pre-push", action="store_true", help="Read Git pre-push ref updates from stdin.")
    mode.add_argument("--revisions", nargs="+", help="Check all blobs reachable from revisions/ranges.")
    parser.add_argument("--limit-mib", type=float, default=DEFAULT_LIMIT_MIB)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit_mib <= 0:
        raise ValueError("--limit-mib must be positive")
    try:
        if args.staged:
            blobs = staged_blobs()
        elif args.pre_push:
            blobs = blobs_from_revisions(pre_push_revisions(sys.stdin))
        else:
            blobs = blobs_from_revisions(args.revisions)
        return check(blobs, args.limit_mib)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: large-file guard could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

