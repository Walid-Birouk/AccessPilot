"""Evidence log: an append-only, hash-chained record of every scan.

Why: under the EAA, being able to show that defects were measured and fixed over
time matters. Each line records a scan's summary and the SHA-256 of its
scan.json, chained to the previous line. Editing or deleting any line breaks the
chain, and editing a scan.json no longer matches its recorded hash; ``verify``
detects both. The log holds no personal data: site, counts, hashes, dates.

Single writer: appends take an exclusive file lock, so two scans finishing at
the same time cannot interleave lines.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _hash(prev: str, record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(prev.encode() + _canonical(body)).hexdigest()


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    try:
        import fcntl
    except ImportError:  # Windows: no advisory locks, single-writer by convention
        yield
        return
    with open(path.with_suffix(path.suffix + ".lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


class EvidenceLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"{self.path}:{n}: not valid JSON") from e

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(self.path):
            prev = GENESIS
            for rec in self.records():
                prev = rec["hash"]
            record = {"kind": kind, "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                      "prev_hash": prev, "payload": payload}
            record["hash"] = _hash(prev, record)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def verify(self, check_files: bool = True) -> tuple[bool, list[str]]:
        """(ok, messages). Checks the chain, and that recorded scan files still match."""
        problems: list[str] = []
        prev = GENESIS
        n = 0
        try:
            for n, rec in enumerate(self.records(), 1):
                if rec.get("prev_hash") != prev:
                    problems.append(f"entry {n}: chain broken (an entry before it was removed or edited)")
                if rec.get("hash") != _hash(rec.get("prev_hash", ""), rec):
                    problems.append(f"entry {n}: content does not match its hash (edited)")
                prev = rec.get("hash", "")
                p = rec.get("payload", {})
                if check_files and p.get("scan_file") and p.get("scan_sha256"):
                    f = (self.path.parent / p["scan_file"]).resolve()
                    if not f.exists():
                        problems.append(f"entry {n}: scan file missing: {p['scan_file']}")
                    elif hashlib.sha256(f.read_bytes()).hexdigest() != p["scan_sha256"]:
                        problems.append(f"entry {n}: scan file modified since logging: {p['scan_file']}")
        except ValueError as e:
            problems.append(str(e))
        if not problems:
            return True, [f"{n} entries, chain intact" + (", scan files match" if check_files else "")]
        return False, problems
