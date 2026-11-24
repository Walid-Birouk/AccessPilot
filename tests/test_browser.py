"""End-to-end: a real Chromium scans a local test shop. Skipped without Chromium."""
import json

import pytest
from fixture_server import serve

from accesspilot.cli import main
from accesspilot.config import load_settings
from accesspilot.evidence import EvidenceLog
from accesspilot.scan.crawler import ScanError, scan_site

pytestmark = pytest.mark.browser


def _settings(chromium, **kw):
    return load_settings(None, chromium_path=chromium, delay_s=0, settle_ms=200, **kw)


def test_scan_finds_defects_and_respects_limits(chromium):
    with serve() as (base, hits):
        scan = scan_site(base, _settings(chromium, per_template=2), log=lambda m: None)
    rules = {f.rule for f in scan.findings}
    # Defects planted in the fixture shop, found despite a CSP that forbids inline scripts.
    assert {"image-alt", "link-name", "select-name", "label", "button-name", "html-has-lang",
            "color-contrast"} <= rules
    tested = {p.template for p in scan.tested_pages}
    assert {"home", "product", "category", "cart", "checkout"} <= tested
    assert sum(1 for p in scan.tested_pages if p.template == "product") == 2  # per_template
    # Never followed: action links, robots-disallowed pages, other sites, files.
    paths = {h.split("?")[0] for h in hits}
    assert not paths & {"/logout", "/cart/add", "/secret/admin", "/catalogue.pdf"}
    assert any(e.startswith("robots_disallowed") for e in scan.events)
    assert next(p for p in scan.pages if p.url.endswith("/broken")).error == "HTTP 404"
    assert all(f.evidence_id.startswith(scan.scan_id) for f in scan.findings)


def test_ignore_robots_and_extra_pages(chromium):
    with serve() as (base, hits):
        scan = scan_site(base, _settings(chromium, respect_robots=False, max_depth=0,
                                         extra_urls=["/secret/admin", "/boom"]),
                         log=lambda m: None)
    urls = {p.url.split("/", 3)[-1]: p for p in scan.pages}
    assert urls["secret/admin"].tested
    assert urls["boom"].error == "HTTP 500" and not urls["boom"].tested


def test_unreachable_site_is_a_clean_error(chromium):
    with pytest.raises(ScanError, match="could be tested"):
        scan_site("http://127.0.0.1:9/", _settings(chromium, page_timeout_s=5), log=lambda m: None)


def test_cli_scan_end_to_end_with_history(chromium, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ACCESSPILOT_CHROMIUM", chromium)
    reports = tmp_path / "reports"
    with serve() as (base, _):
        args = ["scan", base, "--reports-dir", str(reports), "--per-template", "1", "-q", "--json"]
        assert main(args) == 0
        first = json.loads(capsys.readouterr().out)
        assert main(args + ["--fail-on", "serious", "--fail-on-new"]) == 1  # serious defects exist
        second = json.loads(capsys.readouterr().out)
    assert second["diff"]["introduced"] == 0 and second["diff"]["fixed"] == 0
    assert second["diff"]["persisting"] == first["defects"]
    log = EvidenceLog(reports / "evidence.jsonl")
    assert len(list(log.records())) == 2 and log.verify()[0]
    assert main(["verify", "--reports-dir", str(reports)]) == 0


def test_html_report_is_itself_accessible(chromium, tmp_path):
    """Dogfooding: the HTML report must pass the checks it reports on."""
    from playwright.sync_api import sync_playwright

    from accesspilot.plan import build_plan
    from accesspilot.report import render_html
    from accesspilot.scan.crawler import axe_source

    with serve() as (base, _):
        scan = scan_site(base, _settings(chromium, per_template=1), log=lambda m: None)
    page_file = tmp_path / "rapport.html"
    page_file.write_text(render_html(scan, build_plan(scan)), encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium)
        for scheme in ("light", "dark"):
            page = browser.new_page(color_scheme=scheme)
            page.goto(page_file.as_uri())
            page.add_script_tag(content=axe_source())
            res = page.evaluate("async () => (await axe.run(document, {runOnly: {type: 'tag', "
                                "values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations")
            assert res == [], (scheme, [v["id"] for v in res])
        browser.close()
