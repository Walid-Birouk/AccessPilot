"""Claim guard: rules every generated document must pass before it is written.

Automated scans cannot establish conformance, so no output of this tool may
claim it. These checks run on the deterministic documents (as a test) and on
any LLM-written text (as a gate: failing text is discarded, never shipped).

G1  No compliance claim ("conforme au RGAA", "100% accessible", ...).
G2  Every evidence ID cited exists in the scan.
G3  No percentage used as a conformance / coverage rate.
G4  A statement says « non conforme » and carries the not-tested section.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BANNED_PHRASES = [
    "conforme au rgaa", "conforme aux wcag", "conforme au wcag", "conforme à l'eaa",
    "totalement conforme", "partiellement conforme", "entièrement conforme",
    "conformité garantie", "garantit la conformité", "garantir la conformité",
    "certifié accessible", "certifié rgaa", "100% accessible", "100 % accessible",
    "accessible à tous", "fully compliant", "wcag compliant", "rgaa compliant",
    "guaranteed compliance", "is compliant", "est conforme",
]

_PERCENT = re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s?%")
# A percentage is only a problem when it reads as a rate. "zoom à 200 %" is fine.
_RATE_CONTEXT = re.compile(r"conform|taux|score|couvr|couverture|coverage|compliance|compliant|"
                           r"crit[eè]res|respect", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def banned_hits(text: str, extra: list[str] | None = None) -> list[str]:
    low = text.lower()
    # "non conforme" is the required honest status, not a claim: mask it first.
    low = low.replace("est non conforme", "est non-conforme")
    return [p for p in BANNED_PHRASES + [e.lower() for e in extra or []] if p in low]


def rate_sentences(text: str) -> list[str]:
    return [s.strip()[:120] for s in _SENTENCES.split(text)
            if _PERCENT.search(s) and _RATE_CONTEXT.search(s)]


def check_text(text: str, valid_ids: set[str] | None = None,
               cited_ids: list[str] | None = None) -> Verdict:
    reasons = [f"G1 compliance claim: '{h}'" for h in banned_hits(text)]
    if valid_ids is not None:
        for eid in cited_ids or []:
            if eid not in valid_ids:
                reasons.append(f"G2 unknown evidence id: '{eid}'")
    reasons += [f"G3 rate stated: « {s} »" for s in rate_sentences(text)]
    return Verdict(not reasons, reasons)


def check_statement(text: str) -> Verdict:
    v = check_text(text)
    low = text.lower()
    if "non conforme" not in low:
        v.reasons.append("G4 statement must say « non conforme » (no conformance audit exists)")
    if "limites du test automatique" not in low:
        v.reasons.append("G4 statement is missing the « Limites du test automatique » section")
    v.ok = not v.reasons
    return v
