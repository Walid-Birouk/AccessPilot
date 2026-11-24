"""Scan result data model.

A scan is written once to ``scan.json`` and never edited: every report, fix plan,
statement and diff is derived from it. ``SCHEMA_VERSION`` is bumped whenever the
shape changes so older files can be refused with a clear message.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

IMPACTS = ("critical", "serious", "moderate", "minor")
IMPACT_WEIGHT = {"critical": 4, "serious": 3, "moderate": 2, "minor": 1}


def impact_rank(impact: str | None) -> int:
    """Higher is worse. Unknown impact counts as minor."""
    return IMPACT_WEIGHT.get(impact or "minor", 1)


@dataclass
class Finding:
    """One element failing one axe-core rule on one page."""

    evidence_id: str
    fingerprint: str
    rule: str
    impact: str | None
    help: str
    help_url: str
    wcag: list[str]
    url: str
    template: str
    selector: str
    html: str


@dataclass
class ReviewItem:
    """An axe "incomplete" result: automation could not decide, a human must check."""

    rule: str
    help: str
    help_url: str
    url: str
    template: str
    count: int


@dataclass
class Page:
    url: str
    template: str
    status: int | None = None
    final_url: str | None = None
    title: str | None = None
    violations: int = 0
    error: str | None = None

    @property
    def tested(self) -> bool:
        return self.error is None and (self.status is None or self.status < 400)


@dataclass
class Scan:
    scan_id: str
    site: str
    start_url: str
    started: str
    finished: str
    tool_versions: dict[str, str]
    settings: dict[str, Any]
    pages: list[Page] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    needs_review: list[ReviewItem] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    # ---- derived ----

    @property
    def tested_pages(self) -> list[Page]:
        return [p for p in self.pages if p.tested]

    def evidence_ids(self) -> set[str]:
        return {f.evidence_id for f in self.findings}

    def count_by_impact(self) -> dict[str, int]:
        out = {i: 0 for i in IMPACTS}
        for f in self.findings:
            out[f.impact or "minor"] = out.get(f.impact or "minor", 0) + 1
        return out

    # ---- (de)serialisation ----

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1)

    def save(self, path: Path) -> str:
        """Write scan.json; return its SHA-256 (recorded in the evidence log)."""
        data = self.to_json().encode("utf-8")
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scan:
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"scan file has schema_version={version!r}; this AccessPilot reads "
                f"version {SCHEMA_VERSION}. Re-run the scan with this version."
            )
        return cls(
            scan_id=d["scan_id"], site=d["site"], start_url=d["start_url"],
            started=d["started"], finished=d["finished"],
            tool_versions=dict(d["tool_versions"]), settings=dict(d["settings"]),
            pages=[Page(**p) for p in d.get("pages", [])],
            findings=[Finding(**f) for f in d.get("findings", [])],
            needs_review=[ReviewItem(**r) for r in d.get("needs_review", [])],
            events=list(d.get("events", [])),
        )

    @classmethod
    def load(cls, path: Path) -> Scan:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
