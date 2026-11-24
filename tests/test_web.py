"""The public demo (web/): its safety limits, its API, and the accessibility of its own pages."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fixture_server import serve

from accesspilot.config import load_settings
from accesspilot.scan.crawler import ScanError, scan_site
from web.app import DemoApp, Limits, make_server
from web.guard import Limited, RateLimiter, public_url_allowed
from web.shop import Shop, render

# ------------------------------------------------------------------ guard (no network)


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/", "http://100.64.0.1/", "https://93.184.216.34:8443/", "ftp://93.184.216.34/",
    "file:///etc/passwd", "http://user:pw@93.184.216.34/", "http://intranet/", "http://shop.local/",
    "http://metadata.google.internal/", "https://maison-celeste.example/", "not a url",
])
def test_guard_refuses_non_public_addresses(url):
    assert not public_url_allowed(url)


@pytest.mark.parametrize("url", ["https://93.184.216.34/", "http://93.184.216.34:80/x",
                                 "https://[2606:4700:4700::1111]/", "data:image/png;base64,AA"])
def test_guard_allows_public_addresses(url):
    assert public_url_allowed(url)


def test_rate_limiter_per_client_and_global():
    rl = RateLimiter(per_client_per_hour=2, global_per_day=3)
    rl.check("a", now=0)
    rl.check("a", now=1)
    with pytest.raises(Limited, match="live scans for this hour"):
        rl.check("a", now=2)
    rl.check("a", now=3700)            # the hour has passed
    with pytest.raises(Limited, match="today's scan limit"):
        rl.check("b", now=3701)


# ------------------------------------------------------------------ demo shop (no browser)

def test_demo_shop_versions_differ_only_where_declared():
    before = render(Shop("before"), "/products/robe-lin-sable")[2].decode()
    after = render(Shop("after"), "/products/robe-lin-sable")[2].decode()
    assert 'alt="Maison Céleste"' not in before and 'alt="Maison Céleste"' in after
    assert "aria-describeby" in before and "aria-describedby" in after
    assert 'class="promo"' in after and 'class="promo"' not in before
    status, _, body = render(Shop("before", base="/shop/before"), "/")
    assert status == 200 and b'href="/shop/before/cart"' in body
    assert render(Shop("before"), "/nope")[0] == 404
    assert render(Shop("before"), "/robots.txt")[2].startswith(b"User-agent")


# ------------------------------------------------------------------ crawler url_guard

@pytest.mark.browser
def test_url_guard_blocks_requests_and_start_url(chromium):
    settings = load_settings(None, chromium_path=chromium, delay_s=0, settle_ms=100, max_pages=2,
                             respect_robots=False)
    with serve() as (base, hits):
        with pytest.raises(ScanError, match="can be scanned from here"):
            scan_site(base, settings, log=lambda m: None, url_guard=lambda u: False)
        assert hits == []
        # Allow pages, refuse everything else (images): the browser never requests them.
        scan = scan_site(base, settings, log=lambda m: None,
                         url_guard=lambda u: not u.endswith((".png", ".jpg")))
    assert scan.tested_pages
    assert not [h for h in hits if h.endswith((".png", ".jpg"))]


# ------------------------------------------------------------------ server

@pytest.fixture(scope="module")
def demo(tmp_path_factory, chromium):
    """The demo server over freshly built sample reports (one real scan of each shop version)."""
    import os

    from web import samples
    os.environ["ACCESSPILOT_CHROMIUM"] = chromium
    sdir = tmp_path_factory.mktemp("samples")
    samples.build(sdir, log=lambda m: None)
    app = DemoApp(sdir, tmp_path_factory.mktemp("live"),
                  Limits(per_client_per_hour=1, queue_size=4), chromium=chromium, trust_proxy_hops=1)
    httpd = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _post(url, body, ctype="application/json", headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": ctype, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.mark.browser
def test_samples_and_report_api(demo):
    base, _ = demo
    status, headers, body = _get(base + "/api/meta")
    meta = json.loads(body)
    assert status == 200 and [s["id"] for s in meta["samples"]] == ["before", "after"]
    before, after = meta["samples"]
    assert before["site"] == "maison-celeste.example"
    assert after["summary"]["defects"] < before["summary"]["defects"]
    assert after["diff"]["fixed"] > 0 and after["diff"]["introduced"] > 0   # the promo banner
    v = json.loads(_get(base + "/api/report/sample/after")[2])
    assert v["fixes"] and v["fixes"][0]["priority"] == 1 and v["diff"]["fixed_items"]
    assert "127.0.0.1" not in json.dumps(v)          # loopback origin relabelled
    status, headers, body = _get(base + "/reports/sample/before/rapport.html")
    assert status == 200 and "frame-ancestors 'self'" in headers["Content-Security-Policy"]
    status, headers, _ = _get(base + "/reports/sample/before/scan.json")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    assert _get(base + "/reports/sample/before/..%2f..%2fetc")[0] == 404
    assert _get(base + "/reports/sample/zzz/rapport.html")[0] == 404
    assert _get(base + "/api/report/live/abc")[0] == 404
    assert _get(base + "/shop/after/cart")[0] == 200


@pytest.mark.browser
def test_scan_requests_are_validated_and_limited(demo):
    base, app = demo
    assert _post(base + "/api/scan", {"url": "x"}, ctype="text/plain")[0] == 415
    assert _post(base + "/api/scan", b"[1]")[0] == 400
    assert _post(base + "/api/scan", b"x" * 5000)[0] == 413
    status, data = _post(base + "/api/scan", {"url": "http://127.0.0.1:22/"})
    assert status == 400 and "can't be scanned" in data["error"]
    assert _post(base + "/api/scan", {"url": ""})[0] == 400
    # The demo shop scan runs end to end; a second scan from the same visitor is over quota.
    status, job = _post(base + "/api/scan", {"demo": True}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert status == 202 and job["status"] in ("queued", "running")
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        j = json.loads(_get(f"{base}/api/jobs/{job['id']}")[2])
        if j["status"] in ("done", "error"):
            break
        time.sleep(1)
    assert j["status"] == "done", j
    assert j["pages"] and j["result_id"]
    v = json.loads(_get(f"{base}/api/report/live/{j['result_id']}")[2])
    assert v["summary"]["defects"] > 0 and v["site"] == "maison-celeste.example"
    status, data = _post(base + "/api/scan", {"url": "https://93.184.216.34/"},
                         headers={"X-Forwarded-For": "1.2.3.4"})
    assert status == 429 and "live scans" in data["error"]


@pytest.mark.browser
def test_demo_pages_have_no_axe_violations(demo, chromium):
    """The demo of an accessibility tool must itself pass the tool's checks."""
    from playwright.sync_api import sync_playwright

    from accesspilot.config import WCAG_TAGS
    from accesspilot.scan.crawler import axe_source
    base, _ = demo
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium)
        for scheme in ("light", "dark"):
            page = browser.new_page(color_scheme=scheme, bypass_csp=True)
            for route, ready in (("/", "#sample-grid .sample"), ("/#/report/sample/after", ".fix")):
                page.goto(base + route)
                page.wait_for_selector(ready)
                page.add_script_tag(content=axe_source())
                r = page.evaluate("t => axe.run(document, {runOnly: {type: 'tag', values: t}})", WCAG_TAGS)
                results[(scheme, route)] = [(v["id"], [n["target"] for n in v["nodes"]][:3])
                                            for v in r["violations"]]
        browser.close()
    assert all(not v for v in results.values()), results


def test_static_files_exist():
    static = Path(__file__).parents[1] / "web" / "static"
    for name in ("index.html", "app.js", "app.css", "favicon.svg"):
        assert (static / name).is_file()
