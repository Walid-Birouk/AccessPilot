# AccessPilot

**Automated accessibility scans for online shops, built for the European Accessibility Act.**
One command tests a shop's key pages with axe-core in a real browser and gives you a French
report organised the way a theme is fixed (one fix per page template, purchase path first),
a draft *déclaration d'accessibilité*, and a tamper-evident history showing the work over time.

**Try it online:** the [live demo](web/README.md) has sample reports to browse and scans a shop from its address.

```bash
accesspilot scan https://www.example-shop.fr
```

```
Scanning https://www.example-shop.fr (up to 20 pages, 3 per template)...
  home          12 defects  https://www.example-shop.fr/
  product       31 defects  https://www.example-shop.fr/products/robe-lin
  category      18 defects  https://www.example-shop.fr/collections/robes
  cart           9 defects  https://www.example-shop.fr/cart
  ...
example-shop.fr: 104 defects on 11 pages (38 critical, 51 serious, 12 moderate, 3 minor), 14 fixes.
Since the previous scan: 9 fixed, 0 new.
Report: accesspilot-reports/example-shop.fr/2026-11-23T101500Z/rapport.html
```

Prefer a browser? `accesspilot ui` opens a local web interface to start scans, follow their
progress and browse the results (see [Web interface](#web-interface)).

## Why

Since 28 June 2025 the European Accessibility Act applies to e-commerce in the EU. In France
the DGCCRF checks it, and associations have taken retailers to court. Most small and mid-size
shops don't know where they stand, and a full RGAA audit is a significant spend before they know
what is wrong.

Generic scanners answer with hundreds of per-page violations, in English, with no order. A shop
needs something else:

- **What to fix first.** A defect in the product template shows on every product page; one theme
  change fixes all of them. AccessPilot samples a few pages per template, merges findings per
  template and rule, moves elements shared by every page (header logo, menu) into one fix, and
  orders the list by impact and by place in the purchase path (checkout and cart before the home page).
- **A statement to publish.** A draft *déclaration d'accessibilité* in the RGAA model format,
  filled with what was tested, the defect areas, the test environment and the legal recourse text,
  with `[À COMPLÉTER]` where only the owner knows the answer.
- **Proof of progress.** Each scan is compared with the previous one (fixed / new / still present)
  and recorded in a hash-chained log, so you can show that defects were measured and fixed over time.
- **A gate in CI.** `--fail-on serious` or `--fail-on-new` makes a theme deploy fail when it adds
  accessibility regressions.

### What it is not

Automated testing finds only part of accessibility defects. AccessPilot never claims conformance:
reports say so on the first line, list everything automation cannot test, and the statement
declares the site *non conforme* until a human audit says otherwise. A built-in guard rejects any
generated text that claims compliance or states a conformance rate. Use it to find and fix the
detectable defects cheaply, then bring in an auditor for the rest.

## Install

Python 3.11+.

```bash
pipx install "git+https://github.com/Walid-Birouk/AccessPilot"   # or: pip install ...
python -m playwright install chromium                             # the browser used for testing
```

## Use

```bash
# Scan a shop. Add pages the crawler cannot reach by links (cart with items, a form...).
accesspilot scan https://www.example-shop.fr --page /panier --page /contact

# Re-render the reports from a saved scan (no browser), optionally with a baseline
accesspilot report accesspilot-reports/example-shop.fr/2026-11-23T101500Z/scan.json

# Compare two scans
accesspilot diff old/scan.json new/scan.json --fail-on-new

# Check the evidence log and the scan files it references have not been altered
accesspilot verify

# Does the EAA microenterprise exemption likely apply? (SIREN, SIRET, or the shop's address)
accesspilot exemption 652014051
accesspilot exemption https://www.example-shop.fr
```

Each scan writes to `accesspilot-reports/<site>/<timestamp>/`:

| File | What |
| --- | --- |
| `rapport.html` | The report: summary, prioritised fix plan, items to check by hand, pages tested, limits. Self-contained, printable, and itself tested for accessibility. |
| `rapport.md` | The same in Markdown, for a ticket or a pull request. |
| `declaration-accessibilite.BROUILLON.md` | Draft accessibility statement to complete and publish. |
| `plan.json` | The fix plan, machine-readable. |
| `scan.json` | The raw scan: every finding with its page, selector, HTML and evidence ID. Everything else is derived from it. |

and appends one line to `accesspilot-reports/evidence.jsonl`.

### Web interface

```bash
accesspilot ui                 # opens http://127.0.0.1:8765/ in your browser
```

The same tool, without the command line:

- **New scan**: type the shop's address and start; extra pages, page limits and robots.txt are
  under *More options*. Progress shows live (pages tested, scan log), and you can keep browsing
  while it runs.
- **Past scans**, grouped by site, newest first, with defects per scan and the change since the
  previous one. *Scan again* re-runs a site in one click.
- **A scan's page**: the summary, **what changed** since the previous scan (new and fixed defects
  by template and rule), the first fixes to make, the full HTML report, downloads (Markdown
  report, fix plan) and the **draft statement** ready to copy.
- **Exemption check** from a SIREN, a SIRET or the shop's address.
- **Evidence log** check, the same as `accesspilot verify`.

It reads and writes the same `accesspilot-reports/` directory as the CLI (`--reports-dir` to
change it), so scans made either way show up in both. Options: `--port`, `--no-browser`,
`--config`, `--chromium`. It needs no extra dependency.

The interface listens on 127.0.0.1 only and refuses requests from other sites (Host check and a
per-run token on every action), so a web page you visit cannot start scans through it. It is
itself tested with axe-core, in light and dark mode and at phone width.

### In CI

```bash
accesspilot scan https://staging.example-shop.fr --fail-on serious   # exit 1 on any serious/critical defect
accesspilot scan https://www.example-shop.fr --fail-on-new           # exit 1 on regressions only
```

Exit codes: `0` ok, `1` a `--fail-on` / `--fail-on-new` threshold was hit, `2` error.
`--json` prints a summary on stdout. A ready-to-copy weekly GitHub Actions workflow that keeps the
history between runs is in [`examples/github-actions.yml`](examples/github-actions.yml).

### Configuration

Flags cover the common settings (`--max-pages`, `--max-depth`, `--per-template`, `--time-budget`,
`--locale en`). For the rest, or to change which URL patterns mean "product", "cart" and so on,
put an `accesspilot.toml` where you run the command: see
[`examples/accesspilot.toml`](examples/accesspilot.toml).

### Optional: AI-written fix instructions

The fix plan is deterministic: each rule comes with reviewed French guidance. With `--ai`, an LLM
rewrites each fix's instructions for the exact HTML that failed (for example naming the Liquid
snippet's element and showing the corrected markup). Its output must pass the claim guard and may
only cite that fix's evidence IDs; anything else is discarded and the deterministic text is kept.
The LLM never changes what was found.

```bash
export ACCESSPILOT_LLM_API_KEY=...            # any OpenAI-compatible endpoint
export ACCESSPILOT_LLM_MODEL=gpt-4.1-mini     # or mistral-small-latest, a local model...
export ACCESSPILOT_LLM_BASE_URL=https://api.mistral.ai/v1   # default: OpenAI
accesspilot scan https://www.example-shop.fr --ai
```

What is sent: rule ids, template names, CSS selectors and HTML excerpts of the public pages
scanned.

## How it works

```
start URL ─▶ robots.txt ─▶ Chromium (Playwright) ─▶ axe-core on each page ─▶ scan.json
                 │                                                             │
                 └─ links followed: same site, GET only, a few pages per template
                                                                               ▼
           evidence log ◀─ diff with previous scan ◀─ fix plan ─▶ report + draft statement
                                                          ▲
                                                  optional LLM wording (guarded)
```

- **Read-only crawling.** Only GET navigations: nothing is clicked, typed or submitted, so no order,
  account or payment can be triggered. Links that look like actions (logout, add-to-cart,
  `?action=`) are never followed. robots.txt is honoured unless you pass `--ignore-robots` for a
  site you own. Pages, depth, pages per template and total time are capped; requests are spaced;
  a circuit breaker stops on repeated 429/5xx responses.
- **Reliable results.** axe-core 4.14 is bundled (no CDN at scan time, same version every run) and
  injected with the page's Content-Security-Policy bypassed, so a strict CSP cannot silently
  produce an empty scan. Each page waits for the network to settle before testing. A page that
  fails to load is listed as *not tested*, never counted as clean. axe's "incomplete" results are
  reported separately as items to check by hand.
- **Stable comparisons.** Findings carry a fingerprint (template, rule, element) that stays the same
  across scans, so the diff tells real fixes and regressions apart. Templates that failed to load
  in one of the two scans are left out of the comparison.
- **Evidence log.** Each line holds the scan summary and the SHA-256 of its `scan.json`, chained to
  the previous line. `accesspilot verify` detects an edited, deleted or reordered entry and a
  modified scan file. The log holds no personal data.
- **Exemption check.** The EAA exempts microenterprises (fewer than 10 people and turnover or
  balance sheet of at most EUR 2M) from its service requirements. `accesspilot exemption` reads
  the public French business register (recherche-entreprises.api.gouv.fr) and says *likely exempt*,
  *not exempt* or *unknown*, with reasons. Missing data always gives *unknown*. Orientation, not
  legal advice.

The axe rule to RGAA theme mapping in the reports is approximate orientation, and is labelled as
such: exact RGAA criteria are an auditor's call.

## Scanning responsibly

AccessPilot identifies itself in its User-Agent, honours robots.txt, spaces its requests and
stops on server errors. A default scan loads about 20 pages. Scan sites you own or work on; for
anything else, keep the defaults.

## Development

```bash
pip install -e ".[dev]"
python -m playwright install chromium
ruff check .
python -m pytest -q
```

The browser tests start a small local shop (`tests/fixtures/site`, served with a strict CSP, a
robots.txt rule, a 404, a 500 and action links that must not be followed) and scan it with a real
Chromium. They also run axe on AccessPilot's own HTML report and on every view of the web
interface (after running a real scan through it), in light and dark mode, and fail on any
violation. Without Chromium those tests are skipped; set `ACCESSPILOT_CHROMIUM` to use a
specific binary.

## License

MIT for AccessPilot. The bundled axe-core (`accesspilot/scan/vendor/`) is © Deque Systems,
under the Mozilla Public License 2.0.
