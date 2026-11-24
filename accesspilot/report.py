"""Exposure report, in Markdown and in self-contained, accessible HTML.

Rendered from the scan and the fix plan only. The disclaimer and the list of what
automation does not test are written here, in code: no input can drop them.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import Any

from .model import IMPACTS, Scan
from .plan import Fix, template_label
from .rgaa import DISCLAIMER_FR, IMPACT_FR, NOT_TESTED_BY_AUTOMATION

_TAG = re.compile(r"(</?[a-zA-Z][^<>`]*>)")


def _md(text: Any) -> str:
    """Text -> safe Markdown: raw HTML tags go into code spans, pipes are escaped."""
    return _TAG.sub(r"`\1`", str(text or "")).replace("|", "\\|")


def _code(text: str) -> str:
    text = text.replace("\n", " ")
    fence = "``" if "`" in text else "`"
    return f"{fence} {text} {fence}" if fence == "``" else f"`{text}`"


def summary(scan: Scan, plan: list[Fix]) -> dict[str, Any]:
    by_impact = scan.count_by_impact()
    return {
        "site": scan.site,
        "date": scan.started[:10],
        "pages_tested": len(scan.tested_pages),
        "pages_failed": len(scan.pages) - len(scan.tested_pages),
        "defects": len(scan.findings),
        "by_impact": by_impact,
        "fixes": len(plan),
        "templates": sorted({f.template for f in scan.findings}),
        "needs_review": sum(r.count for r in scan.needs_review),
    }


def render_markdown(scan: Scan, plan: list[Fix], diff_md: str | None = None) -> str:
    s = summary(scan, plan)
    out: list[str] = []
    a = out.append
    a(f"# Rapport d'accessibilité : {scan.site}")
    a("")
    a(f"Test automatique du {s['date']} · {s['pages_tested']} pages testées · "
      f"{s['defects']} défauts détectés · {s['fixes']} corrections · "
      f"axe-core {scan.tool_versions.get('axe_core', '?')}")
    a("")
    a(f"> {DISCLAIMER_FR}")
    a("")
    a("## Synthèse")
    a("")
    a("| Gravité | Défauts |")
    a("| --- | ---: |")
    for imp in IMPACTS:
        a(f"| {IMPACT_FR[imp]} | {s['by_impact'].get(imp, 0)} |")
    a("")
    if plan:
        a(f"Les {min(5, len(plan))} premières corrections à faire :")
        a("")
        for fx in plan[:5]:
            a(f"{fx.priority}. {_md(fx.title)} ({template_label(fx.template)}, "
              f"{IMPACT_FR.get(fx.impact or 'minor')}, {fx.count} élément{'s' if fx.count > 1 else ''})")
        a("")
    if s["needs_review"]:
        a(f"{s['needs_review']} éléments n'ont pas pu être évalués automatiquement et doivent "
          "être vérifiés à la main (voir « À vérifier manuellement »).")
        a("")
    if diff_md:
        a(diff_md)
        a("")

    a("## Plan de correction")
    a("")
    a("Une correction par gabarit et par règle : corriger le gabarit corrige toutes les pages "
      "qui l'utilisent. Un élément identique sur plusieurs gabarits (en-tête, menu...) "
      "fait l'objet d'une seule correction.")
    a("")
    for fx in plan:
        a(f"### {fx.priority}. {_md(fx.title)}")
        a("")
        a(f"- **Gabarit** : {template_label(fx.template)} · **gravité** : "
          f"{IMPACT_FR.get(fx.impact or 'minor')} · **éléments** : {fx.count} sur "
          f"{len(fx.pages)} page{'s' if len(fx.pages) > 1 else ''}")
        a(f"- **Règle** : `{fx.rule}`"
          + (f" · WCAG {', '.join(fx.wcag)}" if fx.wcag else "") + f" · {fx.rgaa}")
        a(f"- **Correction** : {_md(fx.instructions)}")
        a(f"- **Exemple** : {_code(fx.sample_selector)} sur {fx.pages[0]}")
        if fx.sample_html:
            a(f"- **Code** : {_code(fx.sample_html[:200])}")
        for note in fx.notes:
            a(f"- {_md(note)}")
        if fx.help_url:
            a(f"- **Documentation** : {fx.help_url}")
        ids = ", ".join(fx.evidence_ids[:4]) + (f" (+{len(fx.evidence_ids) - 4})"
                                                 if len(fx.evidence_ids) > 4 else "")
        a(f"- **Preuves** : {ids}")
        a("")
    if not plan:
        a("Aucun défaut détecté automatiquement sur les pages testées. Ce n'est pas une preuve "
          "d'accessibilité : voir les limites ci-dessous.")
        a("")

    if scan.needs_review:
        a("## À vérifier manuellement")
        a("")
        a("axe-core n'a pas pu conclure sur ces éléments (par exemple un contraste sur une image "
          "de fond). Ils ne sont pas comptés comme défauts.")
        a("")
        a("| Règle | Description | Éléments | Gabarits |")
        a("| --- | --- | ---: | --- |")
        agg: dict[str, list[Any]] = {}
        for r in scan.needs_review:
            e = agg.setdefault(r.rule, [r.help, 0, set()])
            e[1] += r.count
            e[2].add(r.template)
        for rule, (help_, n, tpls) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
            a(f"| `{rule}` | {_md(help_)} | {n} | {', '.join(sorted(tpls))} |")
        a("")

    a("## Pages testées")
    a("")
    a("| Page | Gabarit | Statut | Défauts |")
    a("| --- | --- | --- | ---: |")
    for p in scan.pages:
        status = p.error or str(p.status)
        a(f"| {p.url} | {p.template} | {_md(status)} | {p.violations if p.tested else '—'} |")
    a("")
    failed = [p for p in scan.pages if not p.tested]
    if failed:
        a(f"{len(failed)} page(s) n'ont pas pu être testées : elles ne sont **pas** couvertes "
          "par ce rapport.")
        a("")

    a("## Non testé par l'automatisation")
    a("")
    a("Les points suivants exigent un contrôle humain et ne sont **pas** couverts par ce rapport :")
    a("")
    for item in NOT_TESTED_BY_AUTOMATION:
        a(f"- {item}")
    a("")
    a("## Traçabilité")
    a("")
    a(f"- Identifiant du test : `{scan.scan_id}`, du {scan.started} au {scan.finished}")
    a("- Outils : " + ", ".join(f"{k} {v}" for k, v in scan.tool_versions.items()))
    st = scan.settings
    a(f"- Limites : {st.get('max_pages')} pages, profondeur {st.get('max_depth')}, "
      f"{st.get('per_template')} pages par gabarit, robots.txt "
      f"{'respecté' if st.get('respect_robots') else 'ignoré'}")
    if scan.events:
        a(f"- Événements : {_md('; '.join(scan.events[:20]))}")
    a("")
    return "\n".join(out)


# ---------------------------------------------------------------- HTML

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#555;--line:#d0d0d0;--accent:#0b5cad;--card:#f6f7f9;
--crit:#a4161a;--seri:#9a4a00;--mod:#5c4d00;--min:#3d4f5c}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--fg:#ececec;--muted:#b4b4b4;--line:#3a3f45;
--accent:#7db4ff;--card:#1c2026;--crit:#ff8a8a;--seri:#ffb066;--mod:#e6d36b;--min:#a9c1d4}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.skip{position:absolute;left:-9999px}.skip:focus{left:16px;top:16px;background:var(--bg);padding:8px;z-index:1}
main{max-width:960px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.8rem;margin:.2em 0}h2{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.2em}
h3{font-size:1.1rem;margin:1.6em 0 .4em}
a{color:var(--accent)}a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.meta{color:var(--muted)}
.note{border-left:4px solid var(--accent);background:var(--card);padding:12px 16px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0;padding:0;list-style:none}
.tiles li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.tiles strong{display:block;font-size:1.8rem;font-variant-numeric:tabular-nums}
.fix{border:1px solid var(--line);border-radius:8px;padding:4px 16px 12px;margin:12px 0}
.fix dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:8px 0}
.fix dt{font-weight:600}.fix dd{margin:0;min-width:0}
.badge{display:inline-block;border:1px solid currentColor;border-radius:4px;padding:0 6px;font-size:.85rem;font-weight:600}
.critical{color:var(--crit)}.serious{color:var(--seri)}.moderate{color:var(--mod)}.minor{color:var(--min)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;overflow-wrap:anywhere}
pre{background:var(--card);padding:8px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.table-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;margin:8px 0}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--card)}td.n{text-align:right;font-variant-numeric:tabular-nums}
@media print{.skip{display:none}.fix{break-inside:avoid}}
"""


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def render_html(scan: Scan, plan: list[Fix], diff_html: str | None = None) -> str:
    s = summary(scan, plan)
    h: list[str] = []
    a = h.append
    a("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">")
    a("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    a(f"<title>Rapport d'accessibilité : {_e(scan.site)}</title><style>{_CSS}</style></head><body>")
    a("<a class=\"skip\" href=\"#contenu\">Aller au contenu</a><main id=\"contenu\">")
    a(f"<h1>Rapport d'accessibilité : {_e(scan.site)}</h1>")
    a(f"<p class=\"meta\">Test automatique du {_e(s['date'])} · {s['pages_tested']} pages testées · "
      f"axe-core {_e(scan.tool_versions.get('axe_core', '?'))}</p>")
    a(f"<p class=\"note\">{_e(DISCLAIMER_FR)}</p>")
    a("<h2>Synthèse</h2><ul class=\"tiles\">")
    a(f"<li><strong>{s['defects']}</strong>défauts détectés</li>")
    a(f"<li><strong>{s['fixes']}</strong>corrections à faire</li>")
    for imp in ("critical", "serious"):
        a(f"<li><strong>{s['by_impact'].get(imp, 0)}</strong>défauts {IMPACT_FR[imp]}s</li>")
    a(f"<li><strong>{s['needs_review']}</strong>éléments à vérifier</li></ul>")
    if diff_html:
        a(diff_html)

    a("<h2>Plan de correction</h2>")
    a("<p>Une correction par gabarit et par règle : corriger le gabarit corrige toutes les pages "
      "qui l'utilisent.</p>")
    if not plan:
        a("<p>Aucun défaut détecté automatiquement sur les pages testées. Ce n'est pas une preuve "
          "d'accessibilité : voir les limites ci-dessous.</p>")
    for fx in plan:
        imp = fx.impact or "minor"
        a("<section class=\"fix\">")
        a(f"<h3>{fx.priority}. {_e(fx.title)} <span class=\"badge {imp}\">{IMPACT_FR.get(imp)}</span></h3>")
        a("<dl>")
        a(f"<dt>Gabarit</dt><dd>{_e(template_label(fx.template))}</dd>")
        a(f"<dt>Éléments</dt><dd>{fx.count} sur {len(fx.pages)} page(s)</dd>")
        a(f"<dt>Règle</dt><dd><code>{_e(fx.rule)}</code>"
          + (f" · WCAG {_e(', '.join(fx.wcag))}" if fx.wcag else "") + f" · {_e(fx.rgaa)}</dd>")
        a(f"<dt>Correction</dt><dd>{_e(fx.instructions)}</dd>")
        a(f"<dt>Exemple</dt><dd><code>{_e(fx.sample_selector)}</code> sur "
          f"<a href=\"{_e(fx.pages[0])}\">{_e(fx.pages[0])}</a></dd>")
        if fx.sample_html:
            a(f"<dt>Code</dt><dd><pre><code>{_e(fx.sample_html)}</code></pre></dd>")
        for note in fx.notes:
            a(f"<dt>Note</dt><dd>{_e(note)}</dd>")
        if fx.help_url:
            a(f"<dt>Documentation</dt><dd><a href=\"{_e(fx.help_url)}\">règle {_e(fx.rule)} "
              "(Deque University)</a></dd>")
        a(f"<dt>Preuves</dt><dd><code>{_e(', '.join(fx.evidence_ids[:4]))}</code>"
          + (f" (+{len(fx.evidence_ids) - 4})" if len(fx.evidence_ids) > 4 else "") + "</dd>")
        a("</dl></section>")

    if scan.needs_review:
        a("<h2>À vérifier manuellement</h2>")
        a("<p>axe-core n'a pas pu conclure sur ces éléments. Ils ne sont pas comptés comme défauts.</p>")
        a("<div class=\"table-wrap\"><table><thead><tr><th scope=\"col\">Règle</th>"
          "<th scope=\"col\">Description</th><th scope=\"col\">Éléments</th>"
          "<th scope=\"col\">Gabarits</th></tr></thead><tbody>")
        agg: Counter[str] = Counter()
        helps: dict[str, str] = {}
        tpls: dict[str, set[str]] = {}
        for r in scan.needs_review:
            agg[r.rule] += r.count
            helps[r.rule] = r.help
            tpls.setdefault(r.rule, set()).add(r.template)
        for rule, n in agg.most_common():
            a(f"<tr><td><code>{_e(rule)}</code></td><td>{_e(helps[rule])}</td>"
              f"<td class=\"n\">{n}</td><td>{_e(', '.join(sorted(tpls[rule])))}</td></tr>")
        a("</tbody></table></div>")

    a("<h2>Pages testées</h2><div class=\"table-wrap\"><table><thead><tr>"
      "<th scope=\"col\">Page</th><th scope=\"col\">Gabarit</th><th scope=\"col\">Statut</th>"
      "<th scope=\"col\">Défauts</th></tr></thead><tbody>")
    for p in scan.pages:
        a(f"<tr><td>{_e(p.url)}</td><td>{_e(p.template)}</td><td>{_e(p.error or p.status)}</td>"
          f"<td class=\"n\">{p.violations if p.tested else '—'}</td></tr>")
    a("</tbody></table></div>")

    a("<h2>Non testé par l'automatisation</h2>")
    a("<p>Les points suivants exigent un contrôle humain et ne sont <strong>pas</strong> couverts "
      "par ce rapport :</p><ul>")
    for item in NOT_TESTED_BY_AUTOMATION:
        a(f"<li>{_e(item)}</li>")
    a("</ul>")
    a("<h2>Traçabilité</h2><ul>")
    a(f"<li>Identifiant du test : <code>{_e(scan.scan_id)}</code>, du {_e(scan.started)} "
      f"au {_e(scan.finished)}</li>")
    a("<li>Outils : " + _e(", ".join(f"{k} {v}" for k, v in scan.tool_versions.items())) + "</li>")
    if scan.events:
        a(f"<li>Événements : {_e('; '.join(scan.events[:20]))}</li>")
    a("</ul></main></body></html>")
    return "\n".join(h)
