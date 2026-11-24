/* AccessPilot public demo. Vanilla JS, no build step.
   Every value that comes from a scan (URLs, page titles, failing HTML) is inserted as text,
   never as HTML. */
(() => {
  "use strict";

  const IMPACT_LABEL = { critical: "Critical", serious: "Serious", moderate: "Moderate", minor: "Minor" };
  const TEMPLATE_LABEL = {
    checkout: "Checkout", cart: "Cart", account: "Account", product: "Product page",
    category: "Category page", search: "Search", contact: "Contact", home: "Home page",
    other: "Other", layout: "Shared layout",
  };
  const $ = (sel, root = document) => root.querySelector(sel);
  const landing = $("#landing");
  const view = $("#view");
  const announcer = $("#announcer");
  let meta = null;
  let pollTimer = null;

  // ---------------------------------------------------------------- helpers

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "style") Object.assign(el.style, v);  // CSSOM: allowed by the CSP, unlike style=""
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  const n = (x) => new Intl.NumberFormat("en").format(x);
  const plural = (k, one, many) => `${n(k)} ${k === 1 ? one : many}`;
  const pill = (impact) => h("span", { class: `pill ${impact || "minor"}` }, IMPACT_LABEL[impact] || "Minor");
  const tplLabel = (t) => TEMPLATE_LABEL[t] || t;
  const announce = (msg) => { announcer.textContent = ""; setTimeout(() => { announcer.textContent = msg; }, 50); };

  async function api(path, opts) {
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch { /* not JSON */ }
    if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
    return data;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? iso.slice(0, 10) : d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  }

  function shortUrl(u) {
    try { const p = new URL(u); return (p.pathname + p.search) || "/"; } catch { return u; }
  }

  // ---------------------------------------------------------------- pieces

  function kpis(summary, small) {
    const bi = summary.by_impact || {};
    const tiles = small
      ? [["Defects", summary.defects, ""], ["Critical", bi.critical || 0, "critical"], ["Fixes", summary.fixes, ""]]
      : [["Defects found", summary.defects, ""], ["Critical", bi.critical || 0, "critical"],
         ["Serious", bi.serious || 0, "serious"], ["Fixes to make", summary.fixes, ""]];
    return h("div", { class: small ? "kpis kpis-sm" : "kpis" },
      tiles.map(([label, val, cls]) => h("div", { class: `kpi ${cls}` },
        h("span", { class: "n" }, n(val)), h("span", { class: "l" }, label))));
  }

  function impactBar(summary, impacts) {
    const total = summary.defects || 1;
    const bi = summary.by_impact || {};
    const bar = h("div", { class: "bar", role: "img",
      "aria-label": impacts.map((i) => `${bi[i] || 0} ${i}`).join(", ") },
      impacts.filter((i) => bi[i]).map((i) => h("span", { class: i, style: { width: `${(100 * bi[i]) / total}%` } })));
    const legend = h("ul", { class: "legend", "aria-hidden": "true" },
      impacts.map((i) => h("li", {}, h("i", { class: i }), `${IMPACT_LABEL[i]} ${n(bi[i] || 0)}`)));
    return [bar, legend];
  }

  function fixItem(f) {
    const body = h("div", { class: "fix-body" },
      h("p", {}, f.instructions),
      f.sample_html ? h("pre", {}, h("code", {}, f.sample_html)) : null,
      h("p", { class: "small" },
        f.rgaa ? `RGAA ${f.rgaa}` : "", f.rgaa && f.wcag.length ? " · " : "",
        f.wcag.length ? `WCAG ${f.wcag.join(", ")}` : "", " · ",
        h("a", { href: f.help_url, rel: "noopener noreferrer", target: "_blank" }, `axe rule ${f.rule}`)));
    return h("li", {}, h("details", { class: "fix" },
      h("summary", {},
        h("span", { class: "prio", "aria-label": `Priority ${f.priority}` }, f.priority),
        h("span", {},
          h("span", { class: "fix-title", lang: "fr" }, f.title),
          h("span", { class: "fix-meta" }, pill(f.impact), h("span", { class: "chip" }, f.template_label),
            h("span", {}, `${plural(f.count, "element", "elements")} on ${plural(f.pages, "page", "pages")}`))),
        h("span", { class: "chev", "aria-hidden": "true" })),
      body));
  }

  function diffPanel(d) {
    const LIMIT = 8;
    const list = (items, empty) => items.length
      ? h("ul", {}, items.slice(0, LIMIT).map((it) => h("li", {},
          h("span", {}, h("span", { lang: "fr" }, it.help), " ", h("span", { class: "muted small" }, `· ${it.template}`)),
          h("span", { class: "small muted" }, `×${it.count}`))),
          items.length > LIMIT ? h("li", { class: "muted small" }, `and ${items.length - LIMIT} more in the full report`) : null)
      : h("p", { class: "muted small" }, empty);
    return h("section", { class: "panel", "aria-labelledby": "diff-h" },
      h("h2", { id: "diff-h" }, "Since the previous scan"),
      h("p", { class: "sub" }, "Findings are matched across scans by template, rule and element, so a fix is counted only when the defect is really gone."),
      h("div", { class: "diff-nums" },
        h("div", { class: "diff-num fixed" }, h("span", { class: "n" }, n(d.fixed)), "fixed"),
        h("div", { class: "diff-num new" }, h("span", { class: "n" }, n(d.introduced)), "new"),
        h("div", { class: "diff-num same" }, h("span", { class: "n" }, n(d.persisting)), "still present")),
      h("div", { class: "diff-lists" },
        h("div", {}, h("h3", {}, "Fixed"), list(d.fixed_items, "Nothing fixed yet.")),
        h("div", {}, h("h3", {}, "New"), list(d.introduced_items, "No regressions."))));
  }

  function templatesTable(templates) {
    const max = Math.max(1, ...templates.map((t) => t.defects));
    return h("table", { class: "tpl-table" },
      h("caption", { class: "visually-hidden" }, "Defects by page template"),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Template"), h("th", { scope: "col", class: "num" }, "Pages"),
        h("th", { scope: "col", class: "num" }, "Defects"))),
      h("tbody", {}, templates.map((t) => h("tr", {},
        h("th", { scope: "row" }, t.label),
        h("td", { class: "num" }, n(t.pages)),
        h("td", { class: "num" }, n(t.defects),
          h("span", { class: "meter", style: { width: `${Math.round((60 * t.defects) / max)}px` }, "aria-hidden": "true" }))))));
  }

  function pagesList(pages, live) {
    return h("ul", { class: "pages" }, pages.map((p) => h("li", { class: live ? "appear" : null },
      h("span", { class: "chip" }, tplLabel(p.template)),
      h("span", { class: "url", title: p.url }, shortUrl(p.url)),
      p.error ? h("span", { class: "err" }, "not tested") : h("span", { class: "small" }, plural(p.defects, "defect", "defects")))));
  }

  // ---------------------------------------------------------------- landing

  async function loadLanding() {
    try {
      meta = await api("/api/meta");
    } catch {
      $("#sample-grid").replaceChildren(h("p", { class: "muted" }, "Sample reports could not be loaded."));
      return;
    }
    document.querySelectorAll("[data-version]").forEach((el) => { el.textContent = `v${meta.version}`; });
    document.querySelectorAll("[data-limit]").forEach((el) => { el.textContent = meta.limits[el.dataset.limit]; });
    const grid = $("#sample-grid");
    grid.replaceChildren(...meta.samples.map((s, i) => h("article", { class: "sample" },
      h("span", { class: "tag" }, i === 0 ? "Scan 1" : `Scan ${i + 1} · compared with scan ${i}`),
      h("h3", {}, h("a", { href: `#/report/sample/${s.id}` }, s.title)),
      h("p", {}, s.subtitle),
      kpis(s.summary, false),
      s.diff ? h("div", { class: "diffline" },
        h("span", { class: "pill ok" }, `${n(s.diff.fixed)} fixed`),
        h("span", { class: "pill new" }, `${n(s.diff.introduced)} new`),
        h("span", { class: "chip" }, `${n(s.diff.persisting)} still present`)) : null)));

    const first = meta.samples[0];
    if (first) {
      const v = await api(`/api/report/sample/${first.id}`);
      $("#preview-site").textContent = `${v.site} · ${plural(v.summary.pages_tested, "page", "pages")} tested`;
      $("#preview-kpis").replaceWith(Object.assign(kpis(v.summary, true), { id: "preview-kpis" }));
      $("#preview-fixes").replaceChildren(...v.fixes.slice(0, 3).map((f) => h("li", {},
        pill(f.impact), h("span", {}, h("span", { lang: "fr" }, f.title), h("span", { class: "where" }, f.template_label)))));
    }
  }

  // ---------------------------------------------------------------- report view

  async function showReport(kind, id) {
    const v = await api(`/api/report/${kind}/${id}`);
    const base = `/reports/${kind}/${id}`;
    const title = kind === "sample" ? `${v.title}: ${v.site}` : v.site;
    document.title = `${title} · AccessPilot`;
    const s = v.summary;
    const content = h("div", { class: "view-inner" },
      h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Back to AccessPilot")),
      h("div", { class: "report-head" },
        h("div", {},
          h("h1", { tabindex: "-1", id: "view-title" }, title),
          h("p", {}, `${fmtDate(v.started)} · ${plural(s.pages_tested, "page", "pages")} tested across ${plural(s.templates, "template", "templates")}`,
            s.pages_failed ? ` · ${s.pages_failed} not tested` : "",
            ` · axe-core ${v.tool_versions.axe_core || "?"}`)),
        h("div", { class: "actions" },
          h("a", { class: "btn btn-primary", href: `${base}/rapport.html`, target: "_blank", rel: "noopener" }, "Full report (French)"),
          v.files.includes("declaration-accessibilite.BROUILLON.md")
            ? h("a", { class: "btn btn-ghost", href: `${base}/declaration-accessibilite.BROUILLON.md` }, "Draft statement") : null,
          h("a", { class: "btn btn-ghost", href: `${base}/scan.json` }, "Raw scan (JSON)"))),
      h("p", { class: "notice" }, h("strong", {}, "Automated testing finds only part of accessibility defects. "),
        "This is a list of detected problems, not a compliance verdict. The fix titles and instructions are in French, the language of the shops this tool is for.",
        kind === "live" ? ` This result is private to its link and deleted after ${meta ? meta.limits.keep_hours : 6} hours.` : ""),
      kpis(s, false),
      h("div", { class: "grid-2" },
        h("section", { class: "panel", "aria-labelledby": "sev-h" },
          h("h2", { id: "sev-h" }, "Severity"),
          h("p", { class: "sub" }, `${n(s.defects)} failing elements, plus ${n(s.needs_review)} items automation could not decide, to check by hand.`),
          ...impactBar(s, v.impacts)),
        h("section", { class: "panel", "aria-labelledby": "tpl-h" },
          h("h2", { id: "tpl-h" }, "Where they are"),
          templatesTable(v.templates))),
      v.diff ? diffPanel(v.diff) : null,
      h("section", { class: "panel", "aria-labelledby": "fix-h" },
        h("h2", { id: "fix-h" }, "Fix plan"),
        h("p", { class: "sub" }, `${plural(s.defects, "defect", "defects")} merged into ${plural(s.fixes, "fix", "fixes")}: one per template and rule, shared elements once. Ordered by impact, then by place in the purchase path. Open a fix to see what to change.`),
        h("ol", { class: "fixes" }, v.fixes.map(fixItem))),
      h("section", { class: "panel", "aria-labelledby": "pages-h" },
        h("h2", { id: "pages-h" }, "Pages tested"),
        pagesList(v.pages, false)),
      h("section", { class: "panel", "aria-labelledby": "full-h" },
        h("h2", { id: "full-h" }, "The full report"),
        h("p", { class: "sub" }, "What a shop owner receives: self-contained, printable, and itself tested for accessibility."),
        h("div", { class: "frame-wrap" },
          h("iframe", { src: `${base}/rapport.html`, title: `Full accessibility report for ${v.site} (in French)`, loading: "lazy" }))));
    showView(content);
  }

  // ---------------------------------------------------------------- live scan

  async function startScan(body) {
    const err = $("#scan-error");
    const input = $("#scan-url");
    err.hidden = true;
    input.removeAttribute("aria-invalid");
    const buttons = [$("#scan-submit"), $("#scan-demo")];
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const job = await api("/api/scan", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      location.hash = `#/scan/${job.id}`;
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      if (!body.demo) { input.setAttribute("aria-invalid", "true"); input.focus(); }
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  async function showJob(id) {
    const titleEl = h("h1", { tabindex: "-1", id: "view-title" }, "Starting the scan…");
    const statusText = h("span", {}, "Waiting for a slot…");
    const spinner = h("span", { class: "spinner", "aria-hidden": "true" });
    const bar = h("progress", { max: "8", value: "0", "aria-label": "Pages tested" });
    const list = h("div", {});
    const card = h("div", { class: "progress-card" },
      titleEl, h("p", { class: "status-line", role: "status" }, spinner, statusText), bar, list);
    showView(h("div", { class: "view-inner" }, h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Back to AccessPilot")), card));

    let since = 0;
    let shown = 0;
    const tick = async () => {
      let j;
      try {
        j = await api(`/api/jobs/${id}?since=${since}`);
      } catch (e) {
        spinner.remove();
        card.append(h("div", { class: "err-box", role: "alert" }, e.message === "no such scan"
          ? "This scan has expired. Results are kept for a few hours." : e.message));
        return;
      }
      since = j.next;
      titleEl.textContent = `Scanning ${j.target}`;
      bar.max = j.max_pages;
      bar.value = j.pages.length;
      if (j.pages.length > shown) {
        list.replaceChildren(pagesList(j.pages, true));
        shown = j.pages.length;
      }
      if (j.status === "queued") {
        statusText.textContent = j.position ? `In the queue: ${plural(j.position, "scan", "scans")} ahead of yours.` : "Starting…";
      } else if (j.status === "running") {
        statusText.textContent = `Testing pages in a real browser… ${plural(j.pages.length, "page", "pages")} done, ${j.elapsed_s}s elapsed.`;
      } else if (j.status === "done") {
        announce("Scan finished. Showing the results.");
        location.replace(`#/report/live/${j.result_id}`);
        return;
      } else if (j.status === "error") {
        spinner.remove();
        statusText.textContent = "The scan could not finish.";
        card.append(h("div", { class: "err-box", role: "alert" }, j.error || "Unknown error"),
          h("p", {}, h("a", { href: "#try" }, "Try another address"), " or ", h("a", { href: "#/report/sample/before" }, "open a sample report"), "."));
        return;
      }
      pollTimer = setTimeout(tick, 1200);
    };
    tick();
  }

  // ---------------------------------------------------------------- routing

  function showView(node) {
    landing.hidden = true;
    view.hidden = false;
    view.replaceChildren(node);
    window.scrollTo(0, 0);
    const t = $("#view-title");
    if (t) t.focus();
  }

  function showLanding(anchor) {
    document.title = "AccessPilot · Accessibility scans for online shops";
    view.hidden = true;
    view.replaceChildren();
    landing.hidden = false;
    if (anchor) {
      const el = document.getElementById(anchor);
      if (el) el.scrollIntoView();
    }
  }

  async function route() {
    clearTimeout(pollTimer);
    const hash = location.hash || "#/";
    let m;
    try {
      if ((m = hash.match(/^#\/report\/(sample|live)\/([a-z0-9]+)$/))) {
        await showReport(m[1], m[2]);
      } else if ((m = hash.match(/^#\/scan\/([a-z0-9]+)$/))) {
        await showJob(m[1]);
      } else if (hash.startsWith("#/") || hash === "") {
        showLanding();
      } else {
        showLanding(hash.slice(1));
      }
    } catch (e) {
      showView(h("div", { class: "view-inner" },
        h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Back to AccessPilot")),
        h("h1", { tabindex: "-1", id: "view-title" }, "Not found"),
        h("p", {}, e.message === "no such report"
          ? "This result does not exist or has expired: live results are kept for a few hours."
          : e.message)));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#scan-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const url = $("#scan-url").value.trim();
      if (!url) {
        const err = $("#scan-error");
        err.textContent = "Enter the address of a shop, for example www.example-shop.fr";
        err.hidden = false;
        $("#scan-url").setAttribute("aria-invalid", "true");
        $("#scan-url").focus();
        return;
      }
      startScan({ url });
    });
    $("#scan-demo").addEventListener("click", () => startScan({ demo: true }));
    // In-page anchors (#try, #samples...) while a report is shown: go back to the landing first.
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a[href^='#']");
      if (a && !a.getAttribute("href").startsWith("#/") && !view.hidden) {
        e.preventDefault();
        history.pushState(null, "", a.getAttribute("href"));
        showLanding(a.getAttribute("href").slice(1));
      }
    });
    window.addEventListener("hashchange", route);
    loadLanding();
    route();
  });
})();
