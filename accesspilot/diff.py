"""Compare two scans of the same site: what is new, what was fixed.

Findings are matched by fingerprint (template + rule + element selector), which
is stable across scans, unlike evidence IDs. Only templates tested in both scans
are compared, so a page that failed to load is not mistaken for a fix.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from .model import Finding, Scan, impact_rank
from .rgaa import IMPACT_FR


@dataclass
class ScanDiff:
    old: Scan
    new: Scan
    introduced: list[Finding]
    fixed: list[Finding]
    persisting: int
    compared_templates: list[str]

    @property
    def regressed(self) -> bool:
        return bool(self.introduced)


def diff_scans(old: Scan, new: Scan) -> ScanDiff:
    if old.site != new.site:
        raise ValueError(f"scans are of different sites: {old.site} vs {new.site}")
    common = ({p.template for p in old.tested_pages} & {p.template for p in new.tested_pages})
    old_f = {f.fingerprint: f for f in old.findings if f.template in common}
    new_f = {f.fingerprint: f for f in new.findings if f.template in common}
    introduced = [f for fp, f in new_f.items() if fp not in old_f]
    fixed = [f for fp, f in old_f.items() if fp not in new_f]
    key = lambda f: (-impact_rank(f.impact), f.template, f.rule)  # noqa: E731
    return ScanDiff(old, new, sorted(introduced, key=key), sorted(fixed, key=key),
                    len(set(old_f) & set(new_f)), sorted(common))


def _rows(fs: list[Finding]) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    for f in fs:
        k = (f.template, f.rule, f.impact or "minor")
        out[k] = out.get(k, 0) + 1
    return out


def render_diff_markdown(d: ScanDiff) -> str:
    lines = [f"## Évolution depuis le test du {d.old.started[:10]}", ""]
    lines.append(f"- **{len(d.fixed)}** défauts corrigés, **{len(d.introduced)}** nouveaux, "
                 f"**{d.persisting}** toujours présents (gabarits comparés : "
                 f"{', '.join(d.compared_templates) or 'aucun'}).")
    for title, fs in (("Nouveaux défauts", d.introduced), ("Défauts corrigés", d.fixed)):
        if fs:
            lines += ["", f"### {title}", "", "| Gabarit | Règle | Gravité | Éléments |",
                      "| --- | --- | --- | ---: |"]
            for (tpl, rule, imp), n in sorted(_rows(fs).items(), key=lambda kv: -kv[1]):
                lines.append(f"| {tpl} | `{rule}` | {IMPACT_FR.get(imp, imp)} | {n} |")
    return "\n".join(lines)


def render_diff_html(d: ScanDiff) -> str:
    e = html.escape
    parts = [f"<h2>Évolution depuis le test du {e(d.old.started[:10])}</h2>",
             f"<p><strong>{len(d.fixed)}</strong> défauts corrigés, <strong>{len(d.introduced)}"
             f"</strong> nouveaux, <strong>{d.persisting}</strong> toujours présents.</p>"]
    for title, fs in (("Nouveaux défauts", d.introduced), ("Défauts corrigés", d.fixed)):
        if not fs:
            continue
        parts.append(f"<h3>{title}</h3><div class=\"table-wrap\"><table><thead><tr>"
                     "<th scope=\"col\">Gabarit</th><th scope=\"col\">Règle</th>"
                     "<th scope=\"col\">Gravité</th><th scope=\"col\">Éléments</th></tr></thead><tbody>")
        for (tpl, rule, imp), n in sorted(_rows(fs).items(), key=lambda kv: -kv[1]):
            parts.append(f"<tr><td>{e(tpl)}</td><td><code>{e(rule)}</code></td>"
                         f"<td>{e(IMPACT_FR.get(imp, imp))}</td><td class=\"n\">{n}</td></tr>")
        parts.append("</tbody></table></div>")
    return "\n".join(parts)
