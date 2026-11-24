"""Fix plan: findings -> a prioritised list of fixes, one per (template, rule).

Deterministic. Two consolidations make the list match how a theme is edited:
- Findings of the same rule on the same template are one fix.
- An element that fails on two or more templates with the same selector and
  markup lives in the shared layout (header, footer, menu): it becomes one "layout" fix
  instead of reappearing under every template.

Ordering: impact first (blocking defects before minor ones), then the template's
place in the purchase path (checkout and cart before the home page), then volume.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import TEMPLATE_PRIORITY
from .model import Finding, Scan, impact_rank
from .rgaa import fix_hint, rgaa_theme, wcag_criteria

LAYOUT = "layout"
LAYOUT_LABEL = "commun à plusieurs gabarits (en-tête, pied de page, menu...)"


@dataclass
class Fix:
    priority: int
    template: str
    rule: str
    impact: str | None
    title: str
    instructions: str
    count: int
    pages: list[str]
    evidence_ids: list[str]
    sample_selector: str
    sample_html: str
    help_url: str
    wcag: list[str]
    rgaa: str
    source: str = "rules"
    notes: list[str] = field(default_factory=list)


def _effective_template(findings: list[Finding]) -> dict[str, str]:
    """evidence_id -> template, with shared-layout elements moved to LAYOUT."""
    def element(f: Finding) -> tuple[str, str, str]:
        return (f.rule, f.selector, " ".join(f.html.split()))

    templates_of: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for f in findings:
        if f.selector:
            templates_of[element(f)].add(f.template)
    return {f.evidence_id: (LAYOUT if len(templates_of.get(element(f), ())) >= 2 else f.template)
            for f in findings}


def build_plan(scan: Scan) -> list[Fix]:
    where = _effective_template(scan.findings)
    buckets: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in scan.findings:
        buckets[(where[f.evidence_id], f.rule)].append(f)

    fixes: list[Fix] = []
    for (template, rule), fs in buckets.items():
        first = fs[0]
        title, instructions = fix_hint(rule, first.help)
        fixes.append(Fix(
            priority=0, template=template, rule=rule,
            impact=max((f.impact for f in fs), key=impact_rank),
            title=title, instructions=instructions, count=len(fs),
            pages=sorted({f.url for f in fs}),
            evidence_ids=[f.evidence_id for f in fs],
            sample_selector=first.selector, sample_html=first.html,
            help_url=first.help_url, wcag=wcag_criteria(first.wcag), rgaa=rgaa_theme(rule),
        ))

    def order(fx: Fix) -> tuple[int, int, int, str, str]:
        tpl = -1 if fx.template == LAYOUT else TEMPLATE_PRIORITY.get(fx.template, 50)
        return (-impact_rank(fx.impact), tpl, -fx.count, fx.template, fx.rule)

    fixes.sort(key=order)
    for i, fx in enumerate(fixes, 1):
        fx.priority = i
    return fixes


def template_label(template: str) -> str:
    return LAYOUT_LABEL if template == LAYOUT else template
