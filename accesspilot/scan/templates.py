"""Page templates: classify URLs, and group findings by template.

A shop renders thousands of URLs from a handful of templates (product, category,
cart...). A defect in the product template appears on every product page, and one
fix in the theme closes all of them. So the crawler samples a few pages per
template, and the fix plan is written per template, not per page.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from ..model import Finding, impact_rank

_SLUGGY = re.compile(r"\d|^[0-9a-f-]{16,}$")


def url_shape(url: str) -> str:
    """Coarse URL signature for pages no template pattern matched:
    /blog/2024/ma-recette-123 -> /blog/{x}/{x}."""
    path = urllib.parse.urlparse(url).path or "/"
    parts = [p for p in path.split("/") if p]
    shaped = ["{x}" if (_SLUGGY.search(p) or len(p) > 24) else p.lower() for p in parts[:3]]
    return "/" + "/".join(shaped)


def classify(url: str, templates: dict[str, list[str]]) -> str:
    """Template name for a URL: first matching pattern, else its URL shape."""
    path = (urllib.parse.urlparse(url).path or "/").lower()
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        probe = path + "/"  # "/cart" should match the "/cart/"-style pattern too
    else:
        probe = path
    for name, patterns in templates.items():
        for pat in patterns:
            pat = pat.lower()
            if pat == "/":
                if path in ("/", "") or re.fullmatch(r"/[a-z]{2}(?:-[a-z]{2})?/?", path):
                    return name
            elif pat in path or pat in probe:
                return name
    return url_shape(url)


@dataclass
class RuleGroup:
    rule: str
    impact: str | None
    help: str
    help_url: str
    wcag: list[str]
    count: int = 0
    pages: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)

    @property
    def evidence_ids(self) -> list[str]:
        return [f.evidence_id for f in self.findings]


@dataclass
class TemplateGroup:
    template: str
    pages: set[str] = field(default_factory=set)
    rules: dict[str, RuleGroup] = field(default_factory=dict)

    @property
    def finding_count(self) -> int:
        return sum(r.count for r in self.rules.values())

    @property
    def severity(self) -> int:
        return sum(impact_rank(r.impact) * r.count for r in self.rules.values())

    def sorted_rules(self) -> list[RuleGroup]:
        return sorted(self.rules.values(), key=lambda r: (-impact_rank(r.impact), -r.count, r.rule))


def group_by_template(findings: list[Finding]) -> list[TemplateGroup]:
    """Template groups, worst (severity-weighted) first."""
    groups: dict[str, TemplateGroup] = {}
    for f in findings:
        g = groups.setdefault(f.template, TemplateGroup(f.template))
        g.pages.add(f.url)
        r = g.rules.setdefault(f.rule, RuleGroup(f.rule, f.impact, f.help, f.help_url, f.wcag))
        r.count += 1
        r.pages.add(f.url)
        r.findings.append(f)
    return sorted(groups.values(), key=lambda g: (-g.severity, g.template))
