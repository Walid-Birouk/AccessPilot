"""Crawler: headless Chromium + axe-core. Deterministic, read-only, bounded.

Safety properties (enforced here, not promised):
- GET navigations only. Nothing is clicked, typed or submitted, so no order,
  account or payment can ever be triggered. Links that look like actions
  (logout, add-to-cart, ?action=...) are never followed.
- robots.txt is honoured unless you turn it off for your own site.
- Hard caps on pages, depth, pages per template and wall-clock time; a pause
  between page loads; a circuit breaker on 429/5xx responses.

Reliability choices:
- axe-core is vendored (no CDN at scan time) and injected with CSP bypassed,
  so a strict Content-Security-Policy does not silently produce an empty scan.
- Each page waits for the network to settle (bounded) before axe runs, so
  client-rendered content is tested, and axe itself runs under a timeout.
- A page that fails (timeout, TLS, axe error) is recorded with its error and the
  crawl moves on; it is reported as "not tested", never as "no defects".
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.robotparser
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .. import __version__
from ..config import TEMPLATE_PRIORITY, Settings
from ..model import Finding, Page, ReviewItem, Scan
from .templates import classify

VENDOR = Path(__file__).with_name("vendor")
AXE_VERSION = "4.14.0"
AXE_TIMEOUT_MS = 60_000
MAX_FRONTIER = 2000

_SKIP_EXT = re.compile(
    r"\.(?:pdf|jpe?g|png|gif|webp|avif|svg|ico|zip|gz|mp4|webm|mp3|wav|docx?|xlsx?|pptx?|css|js|json|xml|txt)$",
    re.I)
_ACTION = re.compile(
    r"log-?out|sign-?out|d[ée]connexion|/cart/(?:add|change|clear|update)|add-?to-?cart|"
    r"[?&](?:action|add|remove|delete|logout)=|/wishlist/add|/compare/add", re.I)

Log = Callable[[str], None]


class ScanError(RuntimeError):
    """The scan could not run at all (bad URL, browser missing, site unreachable)."""


def normalise_start_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ScanError(f"not a web address: {url!r}")
    return urllib.parse.urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", p.query, ""))


def bare_host(netloc: str) -> str:
    host = netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    return bare_host(urllib.parse.urlparse(a).netloc) == bare_host(urllib.parse.urlparse(b).netloc)


def canonical(url: str) -> str:
    """Drop fragment and trailing slash, so /cart and /cart/ are one page."""
    p = urllib.parse.urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunparse((p.scheme, p.netloc.lower(), path, "", p.query, ""))


def followable(url: str, site_url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return (p.scheme in ("http", "https") and same_site(url, site_url)
            and not _SKIP_EXT.search(p.path) and not _ACTION.search(url))


def fingerprint(template: str, rule: str, selector: str, html: str = "") -> str:
    """Stable across scans: same template, rule and element = same finding.
    Digits are dropped from the HTML so tokens, prices and ids do not count as changes."""
    snippet = re.sub(r"\d+", "", " ".join(html.split()))[:160]
    return hashlib.sha256(f"{template}|{rule}|{selector}|{snippet}".encode()).hexdigest()[:12]


def axe_source() -> str:
    return (VENDOR / "axe.min.js").read_text(encoding="utf-8")


def axe_locale(locale: str) -> str | None:
    if locale == "fr":
        return (VENDOR / "axe.fr.json").read_text(encoding="utf-8")
    return None


def load_robots(start_url: str, user_agent: str, timeout_s: int,
                url_guard: Callable[[str], bool] | None = None,
                ) -> urllib.robotparser.RobotFileParser | None:
    """Parsed robots.txt, or None when there is none / it cannot be fetched (allow all)."""
    p = urllib.parse.urlparse(start_url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"

    def check(request: httpx.Request) -> None:
        if url_guard and not url_guard(str(request.url)):
            raise httpx.RequestError("blocked by url guard", request=request)

    try:
        with httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout_s,
                          follow_redirects=True, event_hooks={"request": [check]}) as client:
            r = client.get(robots_url)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    rp = urllib.robotparser.RobotFileParser(robots_url)
    rp.parse(r.text.splitlines())
    return rp


_RUN_AXE = """
async ([tags, timeoutMs]) => {
  const run = axe.run(document, {
    runOnly: {type: 'tag', values: tags},
    resultTypes: ['violations', 'incomplete'],
    iframes: false,
  });
  const timeout = new Promise((_, reject) =>
    setTimeout(() => reject(new Error('axe timed out')), timeoutMs));
  const r = await Promise.race([run, timeout]);
  const slim = (items) => items.map(v => ({
    id: v.id, impact: v.impact, help: v.help, helpUrl: v.helpUrl, tags: v.tags,
    nodes: v.nodes.map(n => ({target: n.target, html: n.html}))
  }));
  return {violations: slim(r.violations), incomplete: slim(r.incomplete),
          engine: r.testEngine && r.testEngine.version};
}
"""


def scan_site(start_url: str, settings: Settings, log: Log = print,
              scan_id: str | None = None,
              url_guard: Callable[[str], bool] | None = None) -> Scan:
    """Crawl the site's key templates and run axe-core on each page.

    ``url_guard``, when given, is asked about every request the browser makes
    (navigations, scripts, images...) and about robots.txt; a request it refuses
    is aborted. A public deployment uses it to keep scans off private networks.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise ScanError("playwright is not installed: pip install playwright") from e

    start_url = normalise_start_url(start_url)
    scan_id = scan_id or uuid.uuid4().hex[:10]
    started = datetime.now(UTC).isoformat(timespec="seconds")
    deadline = time.monotonic() + settings.time_budget_s
    if url_guard and not url_guard(start_url):
        raise ScanError(f"{start_url} is not an address that can be scanned from here")
    robots = load_robots(start_url, settings.user_agent, settings.page_timeout_s, url_guard) \
        if settings.respect_robots else None

    pages: list[Page] = []
    findings: list[Finding] = []
    review: list[ReviewItem] = []
    events: list[str] = []
    seen: set[str] = set()
    sampled: dict[str, int] = {}
    explicit = [urllib.parse.urljoin(start_url, u) if u.startswith("/") else normalise_start_url(u)
                for u in settings.extra_urls]
    for u in explicit:
        if not same_site(u, start_url):
            raise ScanError(f"extra page {u} is not on {bare_host(urllib.parse.urlparse(start_url).netloc)}")
    # frontier entries: (url, depth, forced). Forced = given by the user, never skipped by sampling.
    frontier: list[tuple[str, int, bool]] = [(start_url, 0, True)] + [(u, 0, True) for u in explicit]
    site_url = start_url
    breaker = 0
    axe_js = axe_source()
    locale_json = axe_locale(settings.locale)
    engine_version = AXE_VERSION
    browser_version = ""

    def next_entry() -> tuple[str, int, bool] | None:
        # Forced URLs first; then the least-sampled template, shallowest first.
        best_i, best_key = None, None
        for i, (u, d, forced) in enumerate(frontier):
            tpl = classify(u, settings.templates)
            key = (0 if forced else 1, sampled.get(tpl, 0), d,
                   TEMPLATE_PRIORITY.get(tpl, 50), i)
            if best_key is None or key < best_key:
                best_i, best_key = i, key
        return frontier.pop(best_i) if best_i is not None else None

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, executable_path=settings.chromium_path)
        except PlaywrightError as e:
            raise ScanError(
                "could not start Chromium. Run `playwright install chromium`, or point "
                "ACCESSPILOT_CHROMIUM / --chromium at a Chromium binary.\n" + str(e).splitlines()[0]
            ) from e
        browser_version = browser.version
        context = browser.new_context(
            user_agent=settings.user_agent, bypass_csp=True, locale="fr-FR",
            viewport={"width": 1280, "height": 900}, accept_downloads=False,
            service_workers="block",
        )
        if url_guard:
            def _route(route: Any) -> None:
                if url_guard(route.request.url):
                    route.continue_()
                else:
                    route.abort("blockedbyclient")
            context.route("**/*", _route)
        page = context.new_page()
        tested = 0

        while frontier and tested < settings.max_pages:
            if time.monotonic() > deadline:
                events.append("time_budget_exhausted")
                log("  time budget exhausted, stopping.")
                break
            entry = next_entry()
            if entry is None:
                break
            url, depth, forced = entry
            key = canonical(url)
            if key in seen:
                continue
            template = classify(url, settings.templates)
            if not forced and sampled.get(template, 0) >= settings.per_template:
                continue
            if robots and not robots.can_fetch(settings.user_agent, url):
                seen.add(key)
                events.append(f"robots_disallowed {url}")
                continue
            seen.add(key)
            if pages:
                time.sleep(settings.delay_s)

            rec = Page(url=key, template=template)
            pages.append(rec)
            try:
                resp = page.goto(url, timeout=settings.page_timeout_s * 1000, wait_until="domcontentloaded")
            except PlaywrightError as e:
                rec.error = _short(e)
                log(f"  ! {url}: {rec.error}")
                continue
            rec.status = resp.status if resp else None
            rec.final_url = page.url if canonical(page.url) != key else None
            if url_guard and not url_guard(page.url):
                # A redirect is not routed through the guard: check where it landed.
                rec.error = "redirected to an address that cannot be scanned from here"
                log(f"  ! {url}: {rec.error}")
                continue

            if rec.status and (rec.status == 429 or rec.status >= 500):
                breaker += 1
                rec.error = f"HTTP {rec.status}"
                events.append(f"http_{rec.status} {url}")
                if breaker >= settings.breaker_threshold:
                    events.append("circuit_breaker_open")
                    log("  too many 429/5xx responses: circuit breaker open, stopping.")
                    break
                continue
            if rec.status and rec.status >= 400:
                rec.error = f"HTTP {rec.status}"
                log(f"  ! {url}: HTTP {rec.status}")
                continue
            ctype = (resp.headers.get("content-type", "") if resp else "")
            if ctype and "html" not in ctype:
                rec.error = f"not an HTML page ({ctype.split(';')[0]})"
                continue
            if not same_site(page.url, site_url):
                target = urllib.parse.urlparse(page.url).netloc
                if len(pages) == 1:  # the start page redirects to the canonical host: follow it
                    site_url = page.url
                    events.append(f"start_redirect {target}")
                    log(f"  start page redirects to {target}: scanning that site")
                else:
                    rec.error = f"redirected off-site to {target}"
                    log(f"  ! {url}: {rec.error}")
                    continue
            if rec.final_url:
                rec.template = template = classify(page.url, settings.templates)

            try:
                page.wait_for_load_state("networkidle", timeout=max(settings.settle_ms, 1))
            except PlaywrightError:
                pass  # chatty sites never go idle: test what has rendered so far
            try:
                rec.title = (page.title() or "")[:200] or None
                if not page.evaluate("() => typeof window.axe !== 'undefined'"):
                    page.add_script_tag(content=axe_js)
                if locale_json:
                    page.evaluate(f"() => axe.configure({{locale: {locale_json}}})")
                result = page.evaluate(_RUN_AXE, [settings.wcag_tags, AXE_TIMEOUT_MS])
            except PlaywrightError as e:
                rec.error = "axe-core failed: " + _short(e)
                log(f"  ! {url}: {rec.error}")
                continue

            engine_version = result.get("engine") or engine_version
            tested += 1
            sampled[template] = sampled.get(template, 0) + 1
            page_url = canonical(page.url)
            rec.url = page_url
            n_before = len(findings)
            for v in result["violations"]:
                for node in v["nodes"]:
                    selector = _selector(node.get("target"))
                    snippet = (node.get("html") or "")[:400]
                    findings.append(Finding(
                        evidence_id=f"{scan_id}-{len(findings) + 1:04d}",
                        fingerprint=fingerprint(template, v["id"], selector, snippet),
                        rule=v["id"], impact=v.get("impact"), help=v.get("help") or v["id"],
                        help_url=v.get("helpUrl") or "",
                        wcag=[t for t in v.get("tags", []) if t.startswith("wcag") and t[4:5].isdigit()],
                        url=page_url, template=template, selector=selector,
                        html=snippet,
                    ))
            for v in result["incomplete"]:
                review.append(ReviewItem(rule=v["id"], help=v.get("help") or v["id"],
                                         help_url=v.get("helpUrl") or "", url=page_url,
                                         template=template, count=len(v["nodes"])))
            rec.violations = len(findings) - n_before
            log(f"  {template:<10} {rec.violations:>4} defects  {page_url}")

            if depth < settings.max_depth and len(frontier) < MAX_FRONTIER:
                try:
                    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
                except PlaywrightError:
                    hrefs = []
                queued = {canonical(u) for u, _, _ in frontier}
                for href in hrefs:
                    href = href.split("#")[0]
                    c = canonical(href) if href else ""
                    if c and c not in seen and c not in queued and followable(href, site_url):
                        frontier.append((href, depth + 1, False))
                        queued.add(c)

        context.close()
        browser.close()

    if not any(p.tested for p in pages):
        errors = "; ".join(f"{p.url}: {p.error}" for p in pages[:3]) or "no page could be loaded"
        raise ScanError(f"no page of {start_url} could be tested ({errors})")

    return Scan(
        scan_id=scan_id,
        site=bare_host(urllib.parse.urlparse(site_url).netloc),
        start_url=start_url,
        started=started,
        finished=datetime.now(UTC).isoformat(timespec="seconds"),
        tool_versions={"accesspilot": __version__, "axe_core": engine_version,
                       "chromium": browser_version, "ruleset": "+".join(settings.wcag_tags)},
        settings=settings.public(),
        pages=pages, findings=findings, needs_review=review, events=events,
    )


def _selector(target: Any) -> str:
    # axe targets are lists; nested lists mean shadow DOM paths.
    if not target:
        return ""
    return " >> ".join(" ".join(t) if isinstance(t, list) else str(t) for t in target)


def _short(e: Exception) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:200]
