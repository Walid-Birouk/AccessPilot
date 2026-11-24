// AccessPilot local UI. No framework, no build step: DOM built with h(), never innerHTML,
// so text from scanned sites can never become markup.
"use strict";

const TOKEN = document.querySelector('meta[name="accesspilot-token"]').content;
const IMPACTS = ["critical", "serious", "moderate", "minor"];
const STATUS_LABEL = { likely_exempt: "Likely exempt", not_exempt: "Not exempt", unknown: "Unknown" };
const main = document.getElementById("main");
const announcer = document.getElementById("announcer");

let state = { defaults: { max_pages: 20, per_template: 3 }, reports_dir: "" };
let poll = null;          // the running scan: { id, url, next, lines, job, timer }
let lastFinished = null;  // the last scan that ended, still shown on the home page
let firstRender = true;
let lastUrl = "";         // what the user last typed in the scan form, kept across views

// ------------------------------------------------------------------ helpers

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

function announce(text) {
  announcer.textContent = "";
  setTimeout(() => { announcer.textContent = text; }, 50);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AccessPilot-Token": TOKEN },
    body: JSON.stringify(body),
  };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("AccessPilot is not responding. Is `accesspilot ui` still running?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

const enc = encodeURIComponent;
const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;

function fmtDate(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso || "?";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtDuration(s) {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function impactBadge(impact) {
  const i = IMPACTS.includes(impact) ? impact : "minor";
  return h("span", { class: `badge ${i}` }, i);
}

function templateName(t) {
  return t === "layout" ? "shared layout (header, footer, menu)" : t;
}

function reportUrl(site, stamp, file, download) {
  return `/reports/${enc(site)}/${enc(stamp)}/${enc(file)}${download ? "?download" : ""}`;
}

function fieldError(input, errEl, message) {
  if (message) {
    errEl.textContent = message;
    errEl.hidden = false;
    input.setAttribute("aria-invalid", "true");
    input.focus();
  } else {
    errEl.textContent = "";
    errEl.hidden = true;
    input.removeAttribute("aria-invalid");
  }
}

// ------------------------------------------------------------------ routing

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  if (parts[0] === "scan" && parts.length === 3) return ["scan", parts[1], parts[2]];
  if (parts[0] === "exemption") return ["exemption"];
  return ["scans"];
}

async function render() {
  const [view, ...args] = route();
  for (const a of document.querySelectorAll("[data-nav]")) {
    const current = a.dataset.nav === (view === "scan" ? "scans" : view);
    if (current) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  let content;
  try {
    if (view === "scan") content = await scanView(...args);
    else if (view === "exemption") content = exemptionView();
    else content = await scansView();
  } catch (e) {
    document.title = "Error · AccessPilot";
    content = [h("h1", { tabindex: "-1" }, "Something went wrong"),
      h("p", { class: "alert", role: "alert" }, e.message),
      h("p", {}, h("a", { href: "#/" }, "Back to scans"))];
  }
  main.replaceChildren(...[content].flat());
  if (!firstRender) {
    const h1 = main.querySelector("h1");
    if (h1) h1.focus();
    window.scrollTo(0, 0);
  }
  firstRender = false;
  if (view === "scans" && (poll || lastFinished)) attachProgress();
}

// ------------------------------------------------------------------ scans (home)

async function scansView() {
  document.title = "Scans · AccessPilot";
  const sites = await api("/api/sites");
  return [
    h("h1", { tabindex: "-1" }, "Accessibility scans"),
    h("p", { class: "lead" }, "Test a shop's key pages in a real browser, then fix what the report lists, " +
      "page template by template. Results are saved in ", h("code", {}, state.reports_dir), "."),
    newScanSection(),
    h("section", { id: "progress", "aria-labelledby": "progress-h", hidden: true }),
    pastScansSection(sites),
    historySection(),
  ];
}

function newScanSection() {
  const d = state.defaults;
  const err = h("p", { class: "error-text", id: "url-error", hidden: true });
  const url = h("input", { type: "text", id: "url", name: "url", inputmode: "url", autocomplete: "url",
    spellcheck: "false", "aria-describedby": "url-hint url-error", value: lastUrl,
    oninput: (e) => { lastUrl = e.target.value; } });
  const pages = h("textarea", { id: "pages", name: "pages", rows: "3", spellcheck: "false",
    "aria-describedby": "pages-hint" });
  const maxPages = h("input", { type: "number", id: "max-pages", min: "1", max: "500", value: d.max_pages });
  const perTpl = h("input", { type: "number", id: "per-template", min: "1", max: "50", value: d.per_template });
  const robots = h("input", { type: "checkbox", id: "ignore-robots" });
  const submit = h("button", { type: "submit", class: "primary", id: "start" }, "Start scan");
  const busy = poll !== null;
  if (busy) submit.disabled = true;

  const form = h("form", { class: "panel", novalidate: true, onsubmit: async (ev) => {
    ev.preventDefault();
    fieldError(url, err, null);
    if (!url.value.trim()) return fieldError(url, err, "Enter the address of the shop to scan.");
    submit.disabled = true;
    try {
      const job = await api("/api/scans", {
        url: url.value.trim(),
        pages: pages.value.split("\n").map((s) => s.trim()).filter(Boolean),
        max_pages: maxPages.value, per_template: perTpl.value, ignore_robots: robots.checked,
      });
      startPolling(job);
    } catch (e) {
      submit.disabled = false;
      fieldError(url, err, e.message);
    }
  } },
    h("div", { class: "field" },
      h("label", { for: "url" }, "Shop address"),
      h("span", { class: "hint", id: "url-hint" }, "For example https://www.example-shop.fr"),
      url, err),
    h("details", {},
      h("summary", {}, "More options"),
      h("div", {},
        h("div", { class: "field" },
          h("label", { for: "pages" }, "Extra pages to test (optional)"),
          h("span", { class: "hint", id: "pages-hint" },
            "One per line. Pages the crawler cannot reach by links, such as /panier or a product page."),
          pages),
        h("div", { class: "row" },
          h("div", { class: "field" }, h("label", { for: "max-pages" }, "Maximum pages"), maxPages),
          h("div", { class: "field" }, h("label", { for: "per-template" }, "Pages per template"), perTpl)),
        h("div", { class: "field" },
          h("label", { class: "check", for: "ignore-robots" }, robots,
            h("span", {}, "Ignore robots.txt. Only for a site you own or are allowed to test."))))),
    h("div", { class: "actions" }, submit,
      h("span", { class: "muted" }, "Only reads pages: nothing is clicked, typed or bought.")));

  return h("section", { "aria-labelledby": "new-scan-h" }, h("h2", { id: "new-scan-h" }, "New scan"), form);
}

function pastScansSection(sites) {
  const sec = h("section", { "aria-labelledby": "past-h" }, h("h2", { id: "past-h" }, "Past scans"));
  if (!sites.length) {
    sec.append(h("p", {}, "No scans yet. Start one above: it takes a few minutes for about twenty pages."));
    return sec;
  }
  for (const s of sites) {
    const capId = `cap-${s.site}`;
    const rows = s.scans.map((sc) => {
      if (sc.error) {
        return h("tr", {}, h("td", {}, sc.stamp), h("td", { colspan: "5" }, `Cannot be read: ${sc.error}`));
      }
      return h("tr", {},
        h("td", { class: "date" }, h("a", { href: `#/scan/${enc(sc.site)}/${enc(sc.stamp)}` }, fmtDate(sc.started))),
        h("td", { class: "n" }, sc.pages_tested),
        h("td", { class: "n" }, sc.defects),
        h("td", { class: "n" }, sc.by_impact.critical || 0),
        h("td", { class: "n" }, sc.by_impact.serious || 0),
        h("td", {}, changeText(sc.change)));
    });
    sec.append(h("div", { class: "site" },
      h("div", { class: "site-head" },
        h("h3", {}, s.site),
        s.start_url ? h("button", { type: "button", class: "secondary",
          onclick: () => prefill(s.start_url) }, "Scan again",
          h("span", { class: "visually-hidden" }, ` ${s.site}`)) : null),
      h("div", { class: "table-wrap" }, h("table", {},
        h("caption", { id: capId, class: "visually-hidden" }, `Scans of ${s.site}, newest first`),
        h("thead", {}, h("tr", {},
          h("th", { scope: "col" }, "Date"), h("th", { scope: "col", class: "n" }, "Pages"),
          h("th", { scope: "col", class: "n" }, "Defects"), h("th", { scope: "col", class: "n" }, "Critical"),
          h("th", { scope: "col", class: "n" }, "Serious"), h("th", { scope: "col" }, "Since previous"))),
        h("tbody", {}, rows)))));
  }
  return sec;
}

function changeText(change) {
  if (change === undefined || change === null) return h("span", { class: "muted" }, "first scan");
  if (change === 0) return "no change";
  if (change < 0) return h("span", { class: "better" }, `${plural(-change, "defect")} fewer`);
  return h("span", { class: "worse" }, `${plural(change, "defect")} more`);
}

function prefill(startUrl) {
  const input = document.getElementById("url");
  if (!input) return;
  input.value = startUrl;
  lastUrl = startUrl;
  input.focus();
  input.scrollIntoView({ block: "center" });
}

function historySection() {
  const out = h("div", { role: "status" });
  const btn = h("button", { type: "button", class: "secondary", onclick: async () => {
    btn.disabled = true;
    out.replaceChildren("Checking…");
    try {
      const r = await api("/api/verify");
      const cls = r.ok === true ? "note" : r.ok === false ? "alert" : "note";
      const title = r.ok === true ? "History intact." : r.ok === false ? "Problem found." : "";
      out.replaceChildren(h("div", { class: cls }, title ? h("strong", {}, title, " ") : null,
        r.messages.join(" ")));
    } catch (e) {
      out.replaceChildren(h("p", { class: "alert" }, e.message));
    }
    btn.disabled = false;
  } }, "Check the history");
  return h("section", { "aria-labelledby": "hist-h" },
    h("h2", { id: "hist-h" }, "Evidence log"),
    h("p", {}, "Every scan is recorded in a tamper-evident log, so you can show defects were measured and " +
      "fixed over time. Check that no entry or scan file has been altered since."),
    h("div", { class: "actions" }, btn), out);
}

// ------------------------------------------------------------------ live progress

function startPolling(job) {
  if (poll) clearTimeout(poll.timer);
  poll = { id: job.id, url: job.url, next: 0, lines: [], job };
  announce(`Scan of ${job.url} started.`);
  attachProgress();
  tick();
}

async function tick() {
  if (!poll) return;
  try {
    const j = await api(`/api/jobs/${poll.id}?since=${poll.next}`);
    poll.lines.push(...j.lines);
    poll.next = j.next;
    poll.job = j;
    updateProgress();
    if (j.status !== "running") return finishPolling(j);
  } catch (e) {
    poll.job = { ...poll.job, status: "error", error: e.message };
    updateProgress();
    return finishPolling(poll.job);
  }
  poll.timer = setTimeout(tick, 1000);
}

function finishPolling(j) {
  const finished = poll;
  poll = null;
  const start = document.getElementById("start");
  if (start) start.disabled = false;
  if (j.status === "done") {
    const r = j.result;
    announce(`Scan finished: ${plural(r.defects, "defect")} on ${plural(r.pages_tested, "page")}.`);
    refreshPastScans();
  } else {
    announce(`Scan failed: ${j.error}`);
  }
  lastFinished = finished;
}

function attachProgress() {
  const sec = document.getElementById("progress");
  const p = poll || lastFinished;
  if (!sec || !p) return;
  sec.hidden = false;
  sec.replaceChildren(
    h("h2", { id: "progress-h" }, `Scan of ${p.url}`),
    h("div", { class: "panel" },
      h("label", { for: "progress-bar", class: "label" }, "Pages tested"),
      h("progress", { id: "progress-bar", max: p.job.max_pages, value: p.job.pages_done }),
      h("p", { id: "progress-text" }),
      h("div", { id: "progress-result" }),
      h("details", {}, h("summary", {}, "Scan log"),
        h("pre", { class: "log", id: "progress-log", tabindex: "0", "aria-label": "Scan log" }))));
  updateProgress();
}

function updateProgress() {
  const p = poll || lastFinished;
  const bar = document.getElementById("progress-bar");
  if (!p || !bar) return;
  const j = p.job;
  const text = document.getElementById("progress-text");
  const log = document.getElementById("progress-log");
  const res = document.getElementById("progress-result");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
  log.textContent = p.lines.join("\n");
  if (atBottom) log.scrollTop = log.scrollHeight;
  if (j.status === "running") {
    bar.max = j.max_pages;
    bar.value = Math.min(j.pages_done, j.max_pages);
    text.textContent = `${j.pages_done} of up to ${j.max_pages} pages tested · ${fmtDuration(j.elapsed_s || 0)} elapsed. ` +
      "You can browse past scans meanwhile.";
    return;
  }
  bar.max = 1;
  bar.value = 1;
  if (j.status === "done") {
    const r = j.result;
    const diff = r.diff ? ` Since the previous scan: ${r.diff.fixed} fixed, ${r.diff.introduced} new.` : "";
    text.textContent = `Finished: ${plural(r.defects, "defect")} on ${plural(r.pages_tested, "page")}, ` +
      `${plural(r.fixes, "fix", "fixes")} to make.${diff}`;
    res.replaceChildren(h("div", { class: "actions" },
      h("a", { class: "button primary", href: `#/scan/${enc(r.site)}/${enc(r.stamp)}` }, "View results"),
      h("a", { class: "button secondary", href: reportUrl(r.site, r.stamp, "rapport.html") }, "Open full report")));
  } else {
    text.textContent = "";
    res.replaceChildren(h("p", { class: "alert" }, h("strong", {}, "The scan failed. "), j.error || ""));
  }
}

async function refreshPastScans() {
  const old = document.querySelector('section[aria-labelledby="past-h"]');
  if (!old) return;
  try {
    old.replaceWith(pastScansSection(await api("/api/sites")));
  } catch (e) { /* the list stays as it was */ }
}

// ------------------------------------------------------------------ one scan

async function scanView(site, stamp) {
  const s = await api(`/api/scans/${enc(site)}/${enc(stamp)}`);
  document.title = `${site}, ${fmtDate(s.started)} · AccessPilot`;
  const back = h("p", {}, h("a", { href: "#/" }, "All scans"));
  if (s.error) {
    return [back, h("h1", { tabindex: "-1" }, site), h("p", { class: "alert" }, `This scan cannot be read: ${s.error}`)];
  }
  const bi = s.by_impact;
  const files = new Set(s.files);
  const out = [
    back,
    h("h1", { tabindex: "-1" }, `${site}: scan of ${fmtDate(s.started)}`),
    h("p", { class: "lead" }, `${plural(s.pages_tested, "page")} tested` +
      (s.pages_failed ? `, ${s.pages_failed} could not be tested` : "") + ` · axe-core ${s.axe_core || "?"}`),
    h("p", { class: "note" }, "Automated tests find only part of accessibility defects. This is a list of " +
      "detected defects and prioritised fixes, not a conformance audit."),
    h("ul", { class: "tiles", "aria-label": "Summary" },
      h("li", {}, h("strong", {}, s.defects), "defects found"),
      h("li", {}, h("strong", {}, s.fixes ?? "?"), "fixes to make"),
      h("li", {}, h("strong", {}, bi.critical || 0), "critical"),
      h("li", {}, h("strong", {}, bi.serious || 0), "serious"),
      h("li", {}, h("strong", {}, s.needs_review), "to check by hand")),
    h("div", { class: "actions" },
      files.has("rapport.html") ? h("a", { class: "button primary", href: reportUrl(site, stamp, "rapport.html") },
        "Open full report") : null,
      files.has("rapport.md") ? h("a", { class: "button secondary", href: reportUrl(site, stamp, "rapport.md", true) },
        "Download report (Markdown)") : null,
      files.has("plan.json") ? h("a", { class: "button secondary", href: reportUrl(site, stamp, "plan.json", true) },
        "Download fix plan (JSON)") : null),
    changesSection(s.changes),
    topFixesSection(s, site, stamp),
    statementSection(s.statement, site, stamp),
  ];
  if (s.start_url) {
    out.push(h("p", {}, h("a", { href: "#/", onclick: () => { lastUrl = s.start_url; } }, `Scan ${site} again`)));
  }
  return out;
}

function changesSection(c) {
  const sec = h("section", { "aria-labelledby": "changes-h" }, h("h2", { id: "changes-h" }, "What changed"));
  if (!c) {
    sec.append(h("p", {}, "This is the first scan of this site. The next one will show what was fixed and what is new."));
    return sec;
  }
  sec.append(h("p", {}, `Compared with the scan of ${fmtDate(c.previous_date)}: `,
    h("strong", {}, `${c.fixed} fixed`), ", ", h("strong", {}, `${c.introduced} new`),
    `, ${c.persisting} still present.`),
    h("p", { class: "muted" }, "Only page templates tested in both scans are compared: " +
      (c.compared_templates.join(", ") || "none") + "."));
  for (const [title, rows] of [["New defects", c.introduced_rows], ["Fixed defects", c.fixed_rows]]) {
    if (!rows.length) continue;
    sec.append(h("div", { class: "table-wrap" }, h("table", {},
      h("caption", {}, title),
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Template"), h("th", { scope: "col" }, "Rule"),
        h("th", { scope: "col" }, "Impact"), h("th", { scope: "col", class: "n" }, "Elements"))),
      h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, templateName(r.template)), h("td", {}, h("code", {}, r.rule)),
        h("td", {}, impactBadge(r.impact)), h("td", { class: "n" }, r.count)))))));
  }
  return sec;
}

function topFixesSection(s, site, stamp) {
  const sec = h("section", { "aria-labelledby": "fixes-h" }, h("h2", { id: "fixes-h" }, "First fixes to make"));
  if (!s.top_fixes.length) {
    sec.append(h("p", {}, "No defect detected automatically on the pages tested. That is not proof of " +
      "accessibility: the full report lists what automation cannot test."));
    return sec;
  }
  sec.append(h("p", {}, "One fix per page template and rule: fixing the template fixes every page that uses it. " +
    "The full report has the instructions, code samples and evidence for each."),
    h("ol", { class: "fixes" }, s.top_fixes.map((f) => h("li", {}, h("span", { lang: "fr" }, f.title), " ",
      impactBadge(f.impact), h("span", { class: "muted" }, ` ${templateName(f.template)}, ${plural(f.count, "element")}`)))));
  if ((s.fixes || 0) > s.top_fixes.length) {
    sec.append(h("p", {}, h("a", { href: reportUrl(site, stamp, "rapport.html") },
      `See all ${s.fixes} fixes in the full report`)));
  }
  return sec;
}

function statementSection(text, site, stamp) {
  const sec = h("section", { "aria-labelledby": "st-h" }, h("h2", { id: "st-h" }, "Draft accessibility statement"));
  if (!text) {
    sec.append(h("p", {}, "No statement was written for this scan."));
    return sec;
  }
  const status = h("span", { role: "status", class: "muted" });
  const pre = h("pre", { class: "statement", lang: "fr", tabindex: "0", "aria-labelledby": "st-h" }, text);
  sec.append(
    h("p", {}, "The déclaration d'accessibilité in the RGAA model format, filled from this scan. Complete the " +
      "parts marked [À COMPLÉTER] and publish it on your site. It says non conforme until a human audit says otherwise."),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "secondary", onclick: async () => {
        try {
          await navigator.clipboard.writeText(text);
          status.textContent = "Copied.";
        } catch (e) {
          const range = document.createRange();
          range.selectNodeContents(pre);
          getSelection().removeAllRanges();
          getSelection().addRange(range);
          status.textContent = "Selected: press Ctrl+C (or Cmd+C) to copy.";
        }
      } }, "Copy"),
      h("a", { class: "button secondary", href: reportUrl(site, stamp, "declaration-accessibilite.BROUILLON.md", true) },
        "Download (Markdown)"),
      status),
    pre);
  return sec;
}

// ------------------------------------------------------------------ exemption

function exemptionView() {
  document.title = "Exemption check · AccessPilot";
  const err = h("p", { class: "error-text", id: "target-error", hidden: true });
  const input = h("input", { type: "text", id: "target", name: "target", spellcheck: "false",
    autocomplete: "off", "aria-describedby": "target-hint target-error" });
  const btn = h("button", { type: "submit", class: "primary" }, "Check");
  const result = h("div", { id: "exemption-result", "aria-live": "polite" });

  const form = h("form", { class: "panel", novalidate: true, onsubmit: async (ev) => {
    ev.preventDefault();
    fieldError(input, err, null);
    if (!input.value.trim()) return fieldError(input, err, "Enter a SIREN, a SIRET or the shop's address.");
    btn.disabled = true;
    result.replaceChildren(h("p", {}, "Looking it up in the public business register…"));
    try {
      const r = await api("/api/exemption", { target: input.value.trim() });
      result.replaceChildren(exemptionResult(r));
    } catch (e) {
      result.replaceChildren();
      fieldError(input, err, e.message);
    }
    btn.disabled = false;
  } },
    h("div", { class: "field" },
      h("label", { for: "target" }, "SIREN, SIRET or shop address"),
      h("span", { class: "hint", id: "target-hint" },
        "For example 652014051, or https://www.example-shop.fr (its SIREN is read from the legal notice)."),
      input, err),
    h("div", { class: "actions" }, btn));

  return [
    h("h1", { tabindex: "-1" }, "Microenterprise exemption"),
    h("p", { class: "lead" }, "The European Accessibility Act exempts microenterprises providing services " +
      "(fewer than 10 people and turnover or balance sheet of at most EUR 2 million) from its service " +
      "requirements. Check what the public French business register says."),
    form, result,
  ];
}

function exemptionResult(r) {
  const money = (n) => new Intl.NumberFormat(undefined, { style: "currency", currency: "EUR",
    maximumFractionDigits: 0 }).format(n);
  const facts = [["Company", r.company], ["SIREN", r.siren], ["Employees", r.headcount],
    ["Category", r.category], ["Turnover", r.turnover != null ? `${money(r.turnover)} (${r.turnover_year})` : null]]
    .filter(([, v]) => v);
  return h("div", { class: "panel result" },
    h("h2", { class: `status-${r.status}` }, STATUS_LABEL[r.status] || r.status),
    facts.length ? h("dl", { class: "facts" }, facts.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])) : null,
    h("h3", {}, "Why"),
    h("ul", {}, r.reasons.map((x) => h("li", {}, x))),
    r.notes && r.notes.length ? h("p", { class: "muted" }, r.notes.join(" ")) : null,
    h("p", { class: "warn" }, "Orientation only, from public register data; not legal advice. " +
      "The exemption covers services, not products."));
}

// ------------------------------------------------------------------ start

async function start() {
  try {
    state = await api("/api/state");
    if (state.job) {
      if (state.job.status === "running") {
        poll = { id: state.job.id, url: state.job.url, next: 0, lines: [], job: state.job };
        tick();
      } else {
        lastFinished = { id: state.job.id, url: state.job.url, lines: state.job.lines, job: state.job };
      }
    }
  } catch (e) { /* render shows the error */ }
  window.addEventListener("hashchange", render);
  render();
}

start();
