"""Local web UI: API, safety checks, and (with Chromium) the page itself.

The scan itself is replaced by a fake in the API tests, so they need no browser;
the browser tests at the end run a real scan through the page and check the page
with axe-core in light and dark mode.
"""
import http.client
import json
import threading
import time
from contextlib import contextmanager

import pytest
from conftest import finding, make_scan

from accesspilot.scan import crawler
from accesspilot.scan.crawler import ScanError
from accesspilot.ui.server import App, make_server


@contextmanager
def running(app):
    httpd = make_server(app, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def request(port, method, path, body=None, token=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        hdrs["X-AccessPilot-Token"] = token
    hdrs.update(headers or {})
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdrs)
    res = conn.getresponse()
    data = res.read()
    conn.close()
    try:
        parsed = json.loads(data)
    except ValueError:
        parsed = data.decode("utf-8", "replace")
    return res.status, parsed, dict(res.getheaders())


def wait_for(port, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        _, j, _ = request(port, "GET", f"/api/jobs/{job_id}")
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("scan job did not finish")


@pytest.fixture
def fake_scans(monkeypatch):
    """scan_site replaced: each call returns the next scan of the list, logging page lines."""
    scans = [make_scan([finding(i) for i in range(1, 4)], scan_id="s1"),
             make_scan([finding(1), finding(9, rule="label", template="cart")], scan_id="s2",
                       started="2026-02-01T10:00:00+00:00")]
    calls = []

    def fake(url, settings, log, scan_id=None):
        calls.append((url, settings))
        for p in ("home", "product", "cart"):
            log(f"  {p:<10} {1:>4} defects  https://shop.example/{p}")
        return scans[min(len(calls) - 1, len(scans) - 1)]

    monkeypatch.setattr(crawler, "scan_site", fake)
    return calls


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no stray accesspilot.toml
    return App(tmp_path / "reports")


def test_page_is_served_with_token_and_strict_csp(app):
    with running(app) as port:
        status, body, headers = request(port, "GET", "/")
        assert status == 200 and app.token in body
        assert "script-src" not in headers["Content-Security-Policy"]  # 'self' only, no inline
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert request(port, "GET", "/app.js")[0] == 200
        assert request(port, "GET", "/nope")[0] == 404


def test_foreign_host_header_is_refused(app):
    """DNS rebinding: a page on evil.example resolving to 127.0.0.1 must get nothing."""
    with running(app) as port:
        for method, path in (("GET", "/"), ("GET", "/api/sites")):
            assert request(port, method, path, headers={"Host": f"evil.example:{port}"})[0] == 403
        assert request(port, "POST", "/api/scans", {"url": "x.fr"}, token=app.token,
                       headers={"Host": "evil.example"})[0] == 403
        assert request(port, "GET", "/api/sites", headers={"Host": f"localhost:{port}"})[0] == 200


def test_state_changing_requests_need_the_token_and_json(app, fake_scans):
    with running(app) as port:
        assert request(port, "POST", "/api/scans", {"url": "shop.example"})[0] == 403
        assert request(port, "POST", "/api/scans", {"url": "shop.example"}, token="wrong")[0] == 403
        assert request(port, "POST", "/api/exemption", {"target": "1"})[0] == 403
        status, _, _ = request(port, "POST", "/api/scans", {"url": "shop.example"}, token=app.token,
                               headers={"Content-Type": "text/plain"})
        assert status == 415
    assert fake_scans == []


def test_scan_runs_and_history_is_browsable(app, fake_scans):
    with running(app) as port:
        assert request(port, "GET", "/api/sites")[1] == []
        status, job, _ = request(port, "POST", "/api/scans",
                                 {"url": "shop.example", "pages": ["/panier", " "], "max_pages": "7",
                                  "ignore_robots": True}, token=app.token)
        assert status == 202 and job["status"] == "running" and job["url"] == "https://shop.example/"
        first = wait_for(port, job["id"])
        assert first["status"] == "done", first["error"]
        assert first["pages_done"] == 3 and first["max_pages"] == 7
        assert any("defects" in line for line in first["lines"])
        url, settings = fake_scans[0]
        assert settings.extra_urls == ["/panier"] and settings.respect_robots is False

        # Polling from an offset returns only the new lines.
        _, tail, _ = request(port, "GET", f"/api/jobs/{job['id']}?since={first['next'] - 1}")
        assert len(tail["lines"]) == 1

        _, job2, _ = request(port, "POST", "/api/scans", {"url": "shop.example"}, token=app.token)
        second = wait_for(port, job2["id"])
        assert second["status"] == "done" and second["result"]["diff"]["fixed"] == 2

        _, sites, _ = request(port, "GET", "/api/sites")
        assert [s["site"] for s in sites] == ["shop.example"]
        scans = sites[0]["scans"]
        assert len(scans) == 2 and scans[0]["stamp"] == second["result"]["stamp"]  # newest first
        assert scans[0]["change"] == -1 and "change" not in scans[1]

        site, stamp = second["result"]["site"], second["result"]["stamp"]
        _, detail, _ = request(port, "GET", f"/api/scans/{site}/{stamp}")
        assert detail["changes"]["fixed"] == 2 and detail["changes"]["introduced"] == 1
        assert detail["changes"]["introduced_rows"] == [
            {"template": "cart", "rule": "label", "impact": "critical", "count": 1}]
        assert "non conforme" in detail["statement"]
        assert detail["top_fixes"] and {"rapport.html", "scan.json"} <= set(detail["files"])

        _, first_detail, _ = request(port, "GET", f"/api/scans/{site}/{first['result']['stamp']}")
        assert first_detail["changes"] is None

        _, verified, _ = request(port, "GET", "/api/verify")
        assert verified["ok"] is True and "2 entries" in verified["messages"][0]


def test_report_files_are_served_from_an_allowlist_only(app, fake_scans):
    with running(app) as port:
        _, job, _ = request(port, "POST", "/api/scans", {"url": "shop.example"}, token=app.token)
        r = wait_for(port, job["id"])["result"]
        base = f"/reports/{r['site']}/{r['stamp']}"
        status, body, headers = request(port, "GET", f"{base}/rapport.html")
        assert status == 200 and "<h1>" in body
        assert headers["Content-Security-Policy"].startswith("default-src 'none'")
        status, _, headers = request(port, "GET", f"{base}/declaration-accessibilite.BROUILLON.md")
        assert status == 200 and "attachment" in headers["Content-Disposition"]
        for bad in (f"{base}/evidence.jsonl", f"{base}/../../evidence.jsonl",
                    f"/reports/{r['site']}/..%2F..%2F/rapport.html", "/reports/../x/rapport.html",
                    f"/api/scans/{r['site']}/..", "/api/scans/../reports"):
            assert request(port, "GET", bad)[0] == 404, bad


def test_one_scan_at_a_time_and_bad_input(app, monkeypatch):
    release = threading.Event()

    def slow(url, settings, log, scan_id=None):
        release.wait(5)
        return make_scan([])

    monkeypatch.setattr(crawler, "scan_site", slow)
    with running(app) as port:
        assert request(port, "POST", "/api/scans", {"url": "ftp://x"}, token=app.token)[0] == 400
        assert request(port, "POST", "/api/scans", {"url": "x.fr", "max_pages": "lots"},
                       token=app.token)[0] == 400
        assert request(port, "POST", "/api/scans", {"url": "x.fr", "max_pages": 0},
                       token=app.token)[0] == 400
        status, job, _ = request(port, "POST", "/api/scans", {"url": "x.fr"}, token=app.token)
        assert status == 202
        status, err, _ = request(port, "POST", "/api/scans", {"url": "y.fr"}, token=app.token)
        assert status == 409 and "already running" in err["error"]
        _, state, _ = request(port, "GET", "/api/state")
        assert state["job"]["id"] == job["id"] and state["job"]["status"] == "running"
        release.set()
        assert wait_for(port, job["id"])["status"] == "done"


def test_failed_scan_is_reported_not_raised(app, monkeypatch):
    def broken(url, settings, log, scan_id=None):
        log("  ! https://x.fr/: timeout")
        raise ScanError("no page could be tested")

    monkeypatch.setattr(crawler, "scan_site", broken)
    with running(app) as port:
        _, job, _ = request(port, "POST", "/api/scans", {"url": "x.fr"}, token=app.token)
        j = wait_for(port, job["id"])
        assert j["status"] == "error" and "no page could be tested" in j["error"]
        assert request(port, "GET", "/api/sites")[1] == []


def test_unreadable_scan_is_listed_with_its_error(app):
    bad = app.reports_dir / "shop.example" / "2026-01-01T000000Z"
    bad.mkdir(parents=True)
    (bad / "scan.json").write_text('{"schema_version": 1}', encoding="utf-8")
    with running(app) as port:
        _, sites, _ = request(port, "GET", "/api/sites")
        assert "schema_version" in sites[0]["scans"][0]["error"]
        _, detail, _ = request(port, "GET", "/api/scans/shop.example/2026-01-01T000000Z")
        assert "error" in detail


def test_exemption_endpoint(app, monkeypatch):
    from accesspilot import exemption
    record = {"nom_complet": "PETITE BOUTIQUE", "tranche_effectif_salarie": "01",
              "categorie_entreprise": "PME", "etat_administratif": "A",
              "finances": {"2024": {"ca": 300000}}}
    monkeypatch.setattr(exemption, "lookup_siren", lambda siren, client=None: record)
    with running(app) as port:
        status, r, _ = request(port, "POST", "/api/exemption", {"target": "652 014 051"},
                               token=app.token)
        assert status == 200 and r["status"] == "likely_exempt" and r["siren"] == "652014051"
        status, err, _ = request(port, "POST", "/api/exemption", {"target": "123"}, token=app.token)
        assert status == 400 and "not a valid SIREN" in err["error"]
        assert request(port, "POST", "/api/exemption", {"target": " "}, token=app.token)[0] == 400

        def down(siren, client=None):
            raise OSError("network unreachable")
        monkeypatch.setattr(exemption, "lookup_siren", down)
        status, err, _ = request(port, "POST", "/api/exemption", {"target": "652014051"},
                                 token=app.token)
        assert status == 502 and "register could not be reached" in err["error"]


def test_ui_command_is_wired():
    from accesspilot.cli import build_parser
    args = build_parser().parse_args(["ui", "--no-browser", "--port", "0"])
    assert args.func.__name__ == "cmd_ui" and args.port == 0 and args.no_browser


# ---------------------------------------------------------------- in a real browser

AXE_RUN = ("async () => (await axe.run(document, {runOnly: {type: 'tag', "
           "values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','best-practice']}})).violations")


def _axe(page):
    from accesspilot.scan.crawler import axe_source
    page.add_script_tag(content=axe_source())
    return [(v["id"], [n["target"] for n in v["nodes"]][:3]) for v in page.evaluate(AXE_RUN)]


@pytest.mark.browser
def test_ui_runs_a_real_scan_and_is_itself_accessible(chromium, tmp_path, monkeypatch):
    """Dogfooding: start a real scan of the test shop from the page, then check every view with axe."""
    from fixture_server import serve
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "fast.toml"
    cfg.write_text("[scan]\nsettle_ms = 200\ndelay_s = 0\nper_template = 1\n", encoding="utf-8")
    app = App(tmp_path / "reports", config=str(cfg), chromium=chromium)
    with serve() as (shop, _), running(app) as port, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium)
        page = browser.new_page(bypass_csp=True)  # to inject axe; the CSP itself is tested above
        page.goto(f"http://127.0.0.1:{port}/")
        expect(page.get_by_role("heading", name="Accessibility scans")).to_be_visible()
        assert _axe(page) == []

        # Empty address: an error tied to the field, focus moved to it.
        page.get_by_role("button", name="Start scan").click()
        field = page.get_by_label("Shop address")
        expect(field).to_have_attribute("aria-invalid", "true")
        expect(field).to_be_focused()

        field.fill(shop)
        page.get_by_role("button", name="Start scan").click()
        expect(page.get_by_role("link", name="View results")).to_be_visible(timeout=60_000)
        expect(page.locator("#announcer")).to_contain_text("Scan finished")
        expect(page.get_by_role("table")).to_have_count(1)  # the new scan is listed
        assert _axe(page) == []

        page.get_by_role("link", name="View results").click()
        expect(page.get_by_role("heading", level=1)).to_contain_text("scan of")
        expect(page.get_by_role("heading", level=1)).to_be_focused()
        expect(page.get_by_role("heading", name="What changed")).to_be_visible()
        expect(page.get_by_text("first scan of this site")).to_be_visible()
        expect(page.locator("pre.statement")).to_contain_text("non conforme")

        detail = page.url
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme, reduced_motion="reduce")  # no mid-transition colours
            for url, heading in ((f"http://127.0.0.1:{port}/", "Accessibility scans"),
                                 (f"http://127.0.0.1:{port}/#/exemption", "Microenterprise exemption"),
                                 (detail, "What changed")):
                page.goto(url)
                expect(page.get_by_role("heading", name=heading)).to_be_visible()
                assert _axe(page) == [], (scheme, url)

        # Phone width: no horizontal page scroll (wide tables scroll inside their own box).
        page.set_viewport_size({"width": 360, "height": 740})
        for url, heading in ((f"http://127.0.0.1:{port}/", "Past scans"), (detail, "What changed"),
                             (f"http://127.0.0.1:{port}/#/exemption", "Microenterprise exemption")):
            page.goto(url)
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth") <= 360, url
        page.goto(detail)

        page.get_by_role("link", name="Open full report").click()
        expect(page.get_by_role("heading", level=1)).to_contain_text("Rapport d'accessibilité")
        browser.close()
