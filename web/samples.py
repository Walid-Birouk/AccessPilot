"""Build the demo's sample reports by scanning the fictional shop, twice.

``python -m web.samples [out_dir]`` serves Maison Céleste on a loopback port,
scans the ``before`` version, then the ``after`` version with the first scan as
its baseline, and writes both report sets with the same code as
``accesspilot scan``. Nothing here is hand-written: every number on the demo's
sample pages comes from a real scan run when the image is built.
"""
from __future__ import annotations

import http.server
import json
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from accesspilot.cli import _write_outputs
from accesspilot.config import load_settings
from accesspilot.model import Scan
from accesspilot.scan.crawler import scan_site

from .shop import Shop, render

ROOT = Path(__file__).parent
DEFAULT_OUT = ROOT / "samples"
# Reports show this reserved, non-routable domain instead of the loopback address
# the scan really ran against.
DEMO_ORIGIN = "https://maison-celeste.example"
DEMO_SITE = "maison-celeste.example"

SAMPLES = [
    {"id": "before", "version": "before", "baseline": None,
     "title": "First scan",
     "subtitle": "The shop as its theme shipped: what an owner sees on day one."},
    {"id": "after", "version": "after", "baseline": "before",
     "title": "After the first fixes",
     "subtitle": ("Rescanned after fixing the top of the plan: what was fixed, "
                  "and what a new promo banner broke.")},
]


def demo_settings(**overrides):
    base = dict(max_pages=12, per_template=2, max_depth=2, delay_s=0.0, settle_ms=500,
                time_budget_s=180)
    base.update(overrides)
    return load_settings(None, **base)


@contextmanager
def serve_shop(version: str) -> Iterator[str]:
    """Serve one version of the shop on 127.0.0.1; yields its origin."""
    shop = Shop(version=version)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            status, ctype, body = render(shop, self.path)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def relabel(scan: Scan, origin: str) -> Scan:
    """Replace the loopback origin with the demo's display domain everywhere in the scan."""
    text = scan.to_json().replace(origin, DEMO_ORIGIN)
    data = json.loads(text)
    data["site"] = DEMO_SITE
    return Scan.from_dict(data)


def scan_demo_shop(version: str, log: Callable[[str], None] = print, **overrides) -> Scan:
    with serve_shop(version) as origin:
        scan = scan_site(origin + "/", demo_settings(**overrides),
                         lambda m: log(m.replace(origin, DEMO_ORIGIN)))
    return relabel(scan, origin)


def write_report(scan: Scan, out: Path, baseline: Scan | None, log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    scan.save(out / "scan.json")
    result = _write_outputs(scan, out, baseline, False, True, log)
    result["files"].insert(0, "scan.json")
    return result


def build(out_dir: Path = DEFAULT_OUT, log=print) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scans: dict[str, Scan] = {}
    index = []
    for sample in SAMPLES:
        log(f"Scanning the demo shop ({sample['version']})...")
        scan = scan_demo_shop(sample["version"], log)
        scans[sample["id"]] = scan
        baseline = scans.get(sample["baseline"]) if sample["baseline"] else None
        write_report(scan, out_dir / sample["id"], baseline, log)
        index.append({k: sample[k] for k in ("id", "title", "subtitle", "baseline")})
    (out_dir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    log(f"Samples written to {out_dir}")
    return index


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT)
