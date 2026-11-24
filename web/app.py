"""AccessPilot public demo: a landing page, sample reports, and guarded live scans.

Run: ``python -m web`` (listens on $PORT, default 7860, the Hugging Face Spaces port).

This is a different program from the local ``accesspilot ui``: it is meant to be
exposed to anonymous visitors, so instead of trusting its user it limits them.

- Live scans are small (a few pages, one level of links, a short time budget),
  always honour robots.txt, run one at a time from a short queue, and are rate
  limited per visitor and per day.
- Scans can only reach public addresses (see ``guard.py``).
- Live results are reachable only by their random id, are never listed, and are
  deleted after a few hours.
- Everything is served with a strict Content-Security-Policy; scan reports are
  self-contained HTML that may only be framed by this site.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from accesspilot import __version__
from accesspilot.config import load_settings
from accesspilot.diff import diff_scans
from accesspilot.model import IMPACTS, Scan
from accesspilot.plan import LAYOUT
from accesspilot.scan.crawler import ScanError, normalise_start_url, scan_site

from . import samples as samples_mod
from .guard import Limited, RateLimiter, public_url_allowed
from .shop import VERSIONS, Shop
from .shop import render as render_shop

HERE = Path(__file__).parent
STATIC = HERE / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/og.png": ("og.png", "image/png"),
}
REPORT_FILES = {
    "rapport.html": "text/html; charset=utf-8",
    "rapport.md": "text/markdown; charset=utf-8",
    "declaration-accessibilite.BROUILLON.md": "text/markdown; charset=utf-8",
    "plan.json": "application/json",
    "scan.json": "application/json",
}
ID_RE = re.compile(r"^[a-z0-9]{1,32}$")
PAGE_LINE = re.compile(r"^\s{2}(\S+)\s+(\d+) defects\s+(\S+)")
MAX_BODY = 4096

UI_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
          "frame-src 'self'; frame-ancestors 'self' https://huggingface.co; base-uri 'none'; "
          "form-action 'self'; object-src 'none'")
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"
SHOP_CSP = "default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'self'"

TEMPLATE_LABELS = {"checkout": "Checkout", "cart": "Cart", "account": "Account", "product": "Product page",
                   "category": "Category page", "search": "Search", "contact": "Contact",
                   "home": "Home page", "other": "Other", LAYOUT: "Shared layout"}


@dataclass
class Limits:
    max_pages: int = int(os.environ.get("DEMO_MAX_PAGES", "8"))
    per_template: int = 2
    max_depth: int = 1
    time_budget_s: int = int(os.environ.get("DEMO_TIME_BUDGET_S", "90"))
    page_timeout_s: int = 20
    per_client_per_hour: int = int(os.environ.get("DEMO_SCANS_PER_HOUR", "3"))
    global_per_day: int = int(os.environ.get("DEMO_SCANS_PER_DAY", "150"))
    queue_size: int = int(os.environ.get("DEMO_QUEUE", "4"))
    keep_results_s: int = int(os.environ.get("DEMO_KEEP_HOURS", "6")) * 3600
    reuse_result_s: int = 30 * 60

    def public(self) -> dict[str, Any]:
        return {"max_pages": self.max_pages, "time_budget_s": self.time_budget_s,
                "scans_per_hour": self.per_client_per_hour,
                "keep_hours": self.keep_results_s // 3600}


@dataclass
class Job:
    id: str
    target: str            # what the visitor asked for (URL), or "demo"
    client: str
    status: str = "queued"   # queued | running | done | error
    lines: list[str] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    result_id: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None

    def log(self, msg: str) -> None:
        for line in str(msg).splitlines():
            self.lines.append(line)
            m = PAGE_LINE.match(line)
            if m:
                self.pages.append({"template": m.group(1), "defects": int(m.group(2)),
                                   "url": m.group(3)})


class DemoApp:
    def __init__(self, samples_dir: Path, live_dir: Path, limits: Limits | None = None,
                 chromium: str | None = None, trust_proxy_hops: int = 1):
        self.samples_dir = Path(samples_dir)
        self.live_dir = Path(live_dir)
        self.live_dir.mkdir(parents=True, exist_ok=True)
        self.limits = limits or Limits()
        self.chromium = chromium or os.environ.get("ACCESSPILOT_CHROMIUM") or None
        self.trust_proxy_hops = trust_proxy_hops
        self.rate = RateLimiter(self.limits.per_client_per_hour, self.limits.global_per_day)
        self.jobs: dict[str, Job] = {}
        self.queue: deque[Job] = deque()
        self.recent: dict[str, tuple[float, str]] = {}   # target -> (time, result id)
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._views: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self.stats = {"scans_done": 0, "scans_failed": 0}
        threading.Thread(target=self._worker, daemon=True, name="scan-worker").start()

    # ------------------------------------------------------------ samples

    def sample_index(self) -> list[dict[str, Any]]:
        idx = self.samples_dir / "index.json"
        if not idx.is_file():
            return []
        out = []
        for s in json.loads(idx.read_text(encoding="utf-8")):
            try:
                v = self.view("sample", s["id"])
            except LookupError:
                continue
            out.append({**s, "site": v["site"], "summary": v["summary"], "diff": v.get("diff_counts")})
        return out

    # ------------------------------------------------------------ jobs

    def submit(self, body: dict[str, Any], client: str) -> Job:
        if body.get("demo"):
            target = "demo"
        else:
            raw = str(body.get("url") or "").strip()
            if not raw:
                raise ValueError("Enter the address of a shop, for example www.example-shop.fr")
            if len(raw) > 300:
                raise ValueError("That address is too long.")
            try:
                target = normalise_start_url(raw)
            except ScanError as e:
                raise ValueError(f"That doesn't look like a web address: {raw}") from e
            if not public_url_allowed(target):
                raise ValueError("That address can't be scanned from here: it has to be a public "
                                 "website on the standard web ports.")
        with self._lock:
            hit = self.recent.get(target)
            if hit and time.time() - hit[0] < self.limits.reuse_result_s and \
                    (self.live_dir / hit[1] / "scan.json").is_file():
                job = Job(uuid.uuid4().hex[:16], target, client, status="done", result_id=hit[1])
                job.lines.append("This address was scanned a few minutes ago: showing that result.")
                self.jobs[job.id] = job
                return job
            if len(self.queue) >= self.limits.queue_size:
                raise Limited("The demo is busy right now. Try again in a minute, or browse the "
                              "sample reports meanwhile.")
        self.rate.check(client)
        job = Job(uuid.uuid4().hex[:16], target, client)
        with self._wake:
            self.jobs[job.id] = job
            self.queue.append(job)
            self._wake.notify()
        return job

    def job_view(self, job_id: str, since: int = 0) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            raise LookupError("no such scan")
        with self._lock:
            # queue[0] is the scan running now: a queued job's index is the number ahead of it.
            ahead = next((i for i, j in enumerate(self.queue) if j is job), None)
        position = ahead if job.status == "queued" else None
        since = max(0, min(since, len(job.lines)))
        now = time.time()
        return {"id": job.id, "status": job.status,
                "target": "Maison Céleste (demo shop)" if job.target == "demo" else job.target,
                "position": position,
                "lines": job.lines[since:], "next": len(job.lines), "pages": job.pages,
                "max_pages": self.limits.max_pages, "result_id": job.result_id, "error": job.error,
                "elapsed_s": int((job.finished or now) - (job.started or now))}

    def _worker(self) -> None:
        while True:
            with self._wake:
                while not self.queue:
                    self._wake.wait(timeout=600)
                    self._cleanup_locked()
                job = self.queue[0]
            job.status = "running"
            job.started = time.time()
            try:
                result_id = self._run(job)
                job.result_id = result_id
                job.status = "done"
                self.stats["scans_done"] += 1
                with self._lock:
                    self.recent[job.target] = (time.time(), result_id)
            except Exception as e:  # noqa: BLE001 - reported to the visitor
                job.error = _friendly_error(e)
                job.status = "error"
                self.stats["scans_failed"] += 1
            finally:
                job.finished = time.time()
                with self._lock:
                    self.queue.popleft()
                    self._cleanup_locked()

    def _settings(self):
        lim = self.limits
        return load_settings(None, max_pages=lim.max_pages, per_template=lim.per_template,
                             max_depth=lim.max_depth, time_budget_s=lim.time_budget_s,
                             page_timeout_s=lim.page_timeout_s, settle_ms=2000, delay_s=0.5,
                             respect_robots=True, chromium_path=self.chromium)

    def _run(self, job: Job) -> str:
        rid = uuid.uuid4().hex[:16]
        out = self.live_dir / rid
        lim = self.limits
        if job.target == "demo":
            job.log("Scanning Maison Céleste, the fictional demo shop...")
            scan = samples_mod.scan_demo_shop(
                "before", job.log, max_pages=lim.max_pages, per_template=lim.per_template,
                max_depth=2, chromium_path=self.chromium, delay_s=0.2)
        else:
            settings = self._settings()
            job.log(f"Scanning {job.target} (up to {settings.max_pages} pages, "
                    f"{settings.per_template} per template)...")
            scan = scan_site(job.target, settings, job.log, url_guard=public_url_allowed)
        samples_mod.write_report(scan, out, None, lambda _m: None)
        (out / "meta.json").write_text(json.dumps({"target": job.target, "created": time.time()}),
                                       encoding="utf-8")
        job.log(f"Done: {len(scan.findings)} defects on {len(scan.tested_pages)} pages.")
        return rid

    def _cleanup_locked(self) -> None:
        now = time.time()
        for jid in [k for k, j in self.jobs.items() if now - j.created > self.limits.keep_results_s]:
            del self.jobs[jid]
        for t in [t for t, (ts, _) in self.recent.items() if now - ts > self.limits.reuse_result_s]:
            del self.recent[t]
        if not self.live_dir.is_dir():
            return
        for d in self.live_dir.iterdir():
            try:
                if d.is_dir() and now - d.stat().st_mtime > self.limits.keep_results_s:
                    shutil.rmtree(d, ignore_errors=True)
                    self._views.pop(("live", d.name), None)
            except OSError:
                pass

    # ------------------------------------------------------------ results

    def result_dir(self, kind: str, rid: str) -> Path:
        if kind not in ("sample", "live") or not ID_RE.match(rid):
            raise LookupError("no such report")
        root = self.samples_dir if kind == "sample" else self.live_dir
        d = root / rid
        if not (d / "scan.json").is_file():
            raise LookupError("no such report")
        return d

    def view(self, kind: str, rid: str) -> dict[str, Any]:
        """Everything the result page shows, derived from scan.json and plan.json."""
        d = self.result_dir(kind, rid)
        mtime = (d / "scan.json").stat().st_mtime
        hit = self._views.get((kind, rid))
        if hit and hit[0] == mtime:
            return hit[1]
        scan = Scan.load(d / "scan.json")
        plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
        by_impact = scan.count_by_impact()
        templates: dict[str, dict[str, Any]] = {}
        for p in scan.pages:
            t = templates.setdefault(p.template, {"template": p.template,
                                                  "label": TEMPLATE_LABELS.get(p.template, p.template),
                                                  "pages": 0, "defects": 0})
            if p.tested:
                t["pages"] += 1
                t["defects"] += p.violations
        v: dict[str, Any] = {
            "kind": kind, "id": rid, "site": scan.site, "start_url": scan.start_url,
            "started": scan.started, "finished": scan.finished, "tool_versions": scan.tool_versions,
            "summary": {"pages_tested": len(scan.tested_pages),
                        "pages_failed": len(scan.pages) - len(scan.tested_pages),
                        "defects": len(scan.findings), "by_impact": by_impact, "fixes": len(plan),
                        "needs_review": sum(r.count for r in scan.needs_review),
                        "templates": len({p.template for p in scan.tested_pages})},
            "impacts": list(IMPACTS),
            "templates": sorted(templates.values(), key=lambda t: -t["defects"]),
            "pages": [{"url": p.url, "template": p.template, "title": p.title,
                       "defects": p.violations, "error": p.error} for p in scan.pages],
            "fixes": [{"priority": f["priority"], "template": f["template"],
                       "template_label": TEMPLATE_LABELS.get(f["template"], f["template"]),
                       "rule": f["rule"], "impact": f["impact"], "title": f["title"],
                       "instructions": f["instructions"], "count": f["count"],
                       "pages": len(f["pages"]), "rgaa": f["rgaa"], "wcag": f["wcag"],
                       "sample_html": f["sample_html"][:300], "help_url": f["help_url"]}
                      for f in plan],
            "files": [n for n in REPORT_FILES if (d / n).is_file()],
        }
        if kind == "sample":
            idx = {s["id"]: s for s in json.loads((self.samples_dir / "index.json").read_text("utf-8"))}
            meta = idx.get(rid, {})
            v["title"], v["subtitle"] = meta.get("title"), meta.get("subtitle")
            base = meta.get("baseline")
            if base:
                old = Scan.load(self.result_dir("sample", base) / "scan.json")
                dd = diff_scans(old, scan)
                item = lambda f: {"rule": f.rule, "impact": f.impact, "help": f.help,  # noqa: E731
                                  "template": TEMPLATE_LABELS.get(f.template, f.template)}
                v["diff_counts"] = {"fixed": len(dd.fixed), "introduced": len(dd.introduced),
                                    "persisting": dd.persisting}
                v["diff"] = {**v["diff_counts"], "baseline": base,
                             "fixed_items": _group(dd.fixed, item),
                             "introduced_items": _group(dd.introduced, item)}
        self._views[(kind, rid)] = (mtime, v)
        return v


def _group(findings: list, item) -> list[dict[str, Any]]:
    """Group findings by (template, rule) with a count, for a compact list."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for f in findings:
        it = item(f)
        k = (it["template"], it["rule"])
        if k in out:
            out[k]["count"] += 1
        else:
            out[k] = {**it, "count": 1}
    return list(out.values())


def _friendly_error(e: Exception) -> str:
    msg = str(e).strip() or type(e).__name__
    if isinstance(e, ScanError):
        if "could not be tested" in msg:
            return ("No page of this site could be tested. It may block automated browsers, be down, "
                    "or redirect to an address that cannot be scanned from here.")
        return msg.splitlines()[0][:300]
    return "The scan failed unexpectedly. Try again, or try another address."


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    app: DemoApp
    server_version = "AccessPilot-demo"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # one short line per request, no IPs
        if os.environ.get("DEMO_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def client_id(self) -> str:
        xff = [p.strip() for p in self.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
        hops = self.app.trust_proxy_hops
        if hops and len(xff) >= hops:
            return xff[-hops]
        return self.client_address[0]

    # ---- responses

    def _send(self, code: int, body: bytes, ctype: str, csp: str = UI_CSP,
              cache: str = "no-store", extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: Any) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _error(self, code: int, msg: str) -> None:
        self._json(code, {"error": msg})

    # ---- routing

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        u = urlparse(self.path)
        path = u.path
        try:
            if path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                f = STATIC / name
                if not f.is_file():
                    return self._error(404, "not found")
                cache = "no-cache" if name == "index.html" else "public, max-age=300"
                return self._send(200, f.read_bytes(), ctype, cache=cache)
            if path == "/healthz":
                return self._json(200, {"ok": True})
            if path == "/api/meta":
                return self._json(200, {"version": __version__, "limits": self.app.limits.public(),
                                        "samples": self.app.sample_index()})
            m = re.fullmatch(r"/api/report/(sample|live)/([a-z0-9]+)", path)
            if m:
                return self._json(200, self.app.view(m.group(1), m.group(2)))
            m = re.fullmatch(r"/api/jobs/([a-z0-9]+)", path)
            if m:
                since = int((parse_qs(u.query).get("since") or ["0"])[0] or 0)
                return self._json(200, self.app.job_view(m.group(1), since))
            m = re.fullmatch(r"/reports/(sample|live)/([a-z0-9]+)/([A-Za-z.\-]+)", path)
            if m and m.group(3) in REPORT_FILES:
                d = self.app.result_dir(m.group(1), m.group(2))
                f = d / m.group(3)
                if not f.is_file():
                    return self._error(404, "not found")
                extra = {}
                if not m.group(3).endswith(".html"):
                    site = d.name if m.group(1) == "live" else "maison-celeste"
                    extra["Content-Disposition"] = f'attachment; filename="{site}-{m.group(3)}"'
                return self._send(200, f.read_bytes(), REPORT_FILES[m.group(3)], csp=REPORT_CSP,
                                  cache="private, max-age=60", extra=extra)
            m = re.fullmatch(r"/shop/(before|after)(/.*)?", path)
            if m:
                version = m.group(1)
                if version not in VERSIONS:
                    return self._error(404, "not found")
                sub = m.group(2) or "/"
                status, ctype, body = render_shop(Shop(version=version, base=f"/shop/{version}"), sub)
                return self._send(status, body, ctype, csp=SHOP_CSP, cache="public, max-age=300",
                                  extra={"X-Robots-Tag": "noindex"})
            return self._error(404, "not found")
        except LookupError as e:
            return self._error(404, str(e).strip("'\"") or "not found")
        except (ValueError, OSError) as e:
            return self._error(400, str(e))

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if urlparse(self.path).path != "/api/scan":
            return self._error(404, "not found")
        # A JSON content type cannot be sent cross-site without a CORS preflight, which this
        # server never grants: other websites cannot start scans from their visitors' browsers.
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self._error(415, "expected application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            return self._error(413, "request too large")
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._error(400, "invalid JSON")
        try:
            job = self.app.submit(body, self.client_id())
        except Limited as e:
            return self._json(429, {"error": str(e)})
        except ValueError as e:
            return self._error(400, str(e))
        return self._json(202, self.app.job_view(job.id))


def make_server(app: DemoApp, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    samples_dir = Path(os.environ.get("DEMO_SAMPLES_DIR", str(samples_mod.DEFAULT_OUT)))
    if not (samples_dir / "index.json").is_file():
        print("No sample reports yet: building them (about 30 s)...", flush=True)
        samples_mod.build(samples_dir)
    live_dir = Path(os.environ.get("DEMO_LIVE_DIR", "/tmp/accesspilot-live"))
    app = DemoApp(samples_dir, live_dir,
                  trust_proxy_hops=int(os.environ.get("DEMO_TRUST_PROXY_HOPS", "1")))
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "7860"))
    httpd = make_server(app, host, port)
    print(f"AccessPilot demo on http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
