"""A small local web app over the same code as the CLI. Standard library only.

What it does: start a scan from an address and follow its progress, list past
scans per site, show a scan's summary, what changed since the previous scan and
the draft statement, open the full report, run the exemption check and verify
the evidence log. Everything it shows is read from the reports directory, so
scans made from the command line appear too.

Safety: the server listens on the loopback interface only. Because a page on any
other website could try to reach it there, it refuses requests whose Host header
is not a loopback name (DNS rebinding), and every state-changing request (start a
scan, look up a company) must carry a per-run token that only the UI's own page
knows, in a custom header that a cross-site page cannot send without a CORS
preflight this server never grants. Report files are served from an allowlist,
and paths are checked to stay inside the reports directory.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__
from ..model import IMPACTS, Scan

STATIC = Path(__file__).with_name("static")
STATIC_FILES = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                "/app.css": ("app.css", "text/css")}
REPORT_FILES = {
    "rapport.html": "text/html",
    "rapport.md": "text/markdown",
    "declaration-accessibilite.BROUILLON.md": "text/markdown",
    "plan.json": "application/json",
    "scan.json": "application/json",
}
STATEMENT = "declaration-accessibilite.BROUILLON.md"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,200}$")
PAGE_LINE = re.compile(r"^\s{2}\S+\s+\d+ defects\s")
MAX_BODY = 64 * 1024
TOKEN_HEADER = "X-AccessPilot-Token"

UI_CSP = ("default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
          "form-action 'self'")
# Reports are self-contained HTML with an inline stylesheet and links to the scanned site.
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'"


# ------------------------------------------------------------------ scan jobs

@dataclass
class Job:
    id: str
    url: str
    max_pages: int
    status: str = "running"            # running | done | error
    lines: list[str] = field(default_factory=list)
    pages_done: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)

    def log(self, msg: str) -> None:
        for line in str(msg).splitlines() or [""]:
            self.lines.append(line)
            if PAGE_LINE.match(line):
                self.pages_done += 1

    def view(self, since: int = 0) -> dict[str, Any]:
        since = max(0, min(since, len(self.lines)))
        return {"id": self.id, "url": self.url, "status": self.status,
                "max_pages": self.max_pages, "pages_done": self.pages_done,
                "lines": self.lines[since:], "next": len(self.lines),
                "result": self.result, "error": self.error,
                "elapsed_s": int(time.time() - self.started)}


class Busy(Exception):
    """A scan is already running: one at a time keeps the shop and this machine unhurried."""


class App:
    """State shared by request handlers: settings, the reports directory, the scan job."""

    def __init__(self, reports_dir: Path, config: str | None = None,
                 chromium: str | None = None):
        self.reports_dir = Path(reports_dir)
        self.config = config
        self.chromium = chromium
        self.token = secrets.token_urlsafe(24)
        self.job: Job | None = None
        self._lock = threading.Lock()
        self._summaries: dict[Path, tuple[float, dict[str, Any]]] = {}

    # ---- scans

    def settings(self, **overrides: Any):
        from ..config import load_settings
        return load_settings(self.config, chromium_path=self.chromium, **overrides)

    def start_scan(self, body: dict[str, Any]) -> Job:
        from ..scan.crawler import normalise_start_url

        url = normalise_start_url(str(body.get("url") or ""))
        raw_pages = body.get("pages") or []
        if not isinstance(raw_pages, list):
            raise ValueError("pages must be a list of addresses")
        pages = [str(p).strip() for p in raw_pages if str(p).strip()]
        overrides: dict[str, Any] = {"extra_urls": pages or None}
        for key in ("max_pages", "per_template"):
            if body.get(key) not in (None, ""):
                try:
                    overrides[key] = int(body[key])
                except (TypeError, ValueError):
                    raise ValueError(f"{key.replace('_', ' ')} must be a whole number") from None
        if body.get("ignore_robots"):
            overrides["respect_robots"] = False
        settings = self.settings(**overrides)
        with self._lock:
            if self.job and self.job.status == "running":
                raise Busy("a scan is already running: wait for it to finish")
            job = Job(uuid.uuid4().hex[:12], url, settings.max_pages)
            self.job = job
        job.log(f"Scanning {url} (up to {settings.max_pages} pages, "
                f"{settings.per_template} per template)...")
        threading.Thread(target=self._run, args=(job, settings), daemon=True,
                         name=f"scan-{job.id}").start()
        return job

    def _run(self, job: Job, settings: Any) -> None:
        try:
            from ..cli import run_scan
            _, result = run_scan(job.url, settings, self.reports_dir, job.log)
            out = Path(result["out"])
            job.result = {**result, "site": out.parent.name, "stamp": out.name}
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - reported to the page, not raised
            job.error = str(e) or type(e).__name__
            job.status = "error"

    # ---- reading the reports directory

    def scan_dir(self, site: str, stamp: str) -> Path:
        if not (SAFE_NAME.match(site) and SAFE_NAME.match(stamp)):
            raise LookupError("no such scan")
        d = (self.reports_dir / site / stamp).resolve()
        if self.reports_dir.resolve() not in d.parents or not (d / "scan.json").is_file():
            raise LookupError("no such scan")
        return d

    def _scan_dirs(self, site_dir: Path) -> list[Path]:
        return sorted((p.parent for p in site_dir.glob("*/scan.json")), key=lambda p: p.name)

    def _summary(self, d: Path) -> dict[str, Any]:
        """Summary of one scan directory, cached on scan.json's modification time."""
        path = d / "scan.json"
        mtime = path.stat().st_mtime
        hit = self._summaries.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            scan = Scan.load(path)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            s: dict[str, Any] = {"site": d.parent.name, "stamp": d.name, "error": str(e)}
        else:
            fixes = None
            plan = d / "plan.json"
            if plan.is_file():
                try:
                    fixes = len(json.loads(plan.read_text(encoding="utf-8")))
                except (ValueError, OSError):
                    pass
            s = {"site": d.parent.name, "stamp": d.name, "scan_id": scan.scan_id,
                 "start_url": scan.start_url, "started": scan.started,
                 "pages_tested": len(scan.tested_pages),
                 "pages_failed": len(scan.pages) - len(scan.tested_pages),
                 "defects": len(scan.findings), "by_impact": scan.count_by_impact(),
                 "fixes": fixes, "needs_review": sum(r.count for r in scan.needs_review)}
        self._summaries[path] = (mtime, s)
        return s

    def sites(self) -> list[dict[str, Any]]:
        out = []
        if not self.reports_dir.is_dir():
            return out
        for site_dir in self.reports_dir.iterdir():
            if not site_dir.is_dir() or not SAFE_NAME.match(site_dir.name):
                continue
            dirs = self._scan_dirs(site_dir)
            if not dirs:
                continue
            scans = [dict(self._summary(d)) for d in dirs]
            prev = None
            for s in scans:
                if prev is not None and "error" not in s and "error" not in prev:
                    s["change"] = s["defects"] - prev["defects"]
                prev = s
            scans.reverse()  # newest first
            out.append({"site": site_dir.name, "scans": scans,
                        "start_url": next((s["start_url"] for s in scans if "start_url" in s), None)})
        out.sort(key=lambda x: x["scans"][0]["stamp"], reverse=True)
        return out

    def scan_detail(self, site: str, stamp: str) -> dict[str, Any]:
        from ..diff import diff_scans

        d = self.scan_dir(site, stamp)
        detail = dict(self._summary(d))
        if "error" in detail:
            return detail
        scan = Scan.load(d / "scan.json")
        detail["axe_core"] = scan.tool_versions.get("axe_core")
        detail["files"] = [f for f in REPORT_FILES if (d / f).is_file()]
        plan = d / "plan.json"
        detail["top_fixes"] = []
        if plan.is_file():
            fixes = json.loads(plan.read_text(encoding="utf-8"))
            detail["top_fixes"] = [{k: fx.get(k) for k in ("priority", "title", "template", "impact",
                                                           "count", "rule")} for fx in fixes[:5]]
        st = d / STATEMENT
        detail["statement"] = st.read_text(encoding="utf-8") if st.is_file() else None

        detail["changes"] = None
        earlier = [p for p in self._scan_dirs(d.parent) if p.name < d.name]
        for prev_dir in reversed(earlier):
            try:
                old = Scan.load(prev_dir / "scan.json")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            df = diff_scans(old, scan)
            detail["changes"] = {
                "previous_stamp": prev_dir.name, "previous_date": old.started,
                "fixed": len(df.fixed), "introduced": len(df.introduced),
                "persisting": df.persisting, "compared_templates": df.compared_templates,
                "introduced_rows": _rows(df.introduced), "fixed_rows": _rows(df.fixed)}
            break
        return detail

    def verify(self) -> dict[str, Any]:
        from ..evidence import EvidenceLog
        path = self.reports_dir / "evidence.jsonl"
        if not path.exists():
            return {"ok": None, "messages": ["No evidence log yet: it is created by the first scan."]}
        ok, messages = EvidenceLog(path).verify()
        return {"ok": ok, "messages": messages}

    def exemption(self, target: str) -> dict[str, Any]:
        from ..exemption import check_target
        notes: list[str] = []
        res = check_target(target, log=notes.append)
        return {**res.__dict__, "notes": notes}

    def state(self) -> dict[str, Any]:
        s = self.settings()
        return {"version": __version__, "reports_dir": str(self.reports_dir.resolve()),
                "defaults": {"max_pages": s.max_pages, "per_template": s.per_template},
                "job": self.job.view() if self.job else None}


def _rows(findings: list[Any]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, str, str], int] = {}
    for f in findings:
        k = (f.template, f.rule, f.impact or "minor")
        agg[k] = agg.get(k, 0) + 1
    rows = [{"template": t, "rule": r, "impact": i, "count": n} for (t, r, i), n in agg.items()]
    return sorted(rows, key=lambda x: (IMPACTS.index(x["impact"]) if x["impact"] in IMPACTS else 9,
                                       -x["count"]))


# ------------------------------------------------------------------ HTTP

class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = f"AccessPilot/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # quiet: the terminal is not a request log
        pass

    # ---- plumbing

    def _send(self, code: int, body: bytes, ctype: str, csp: str = UI_CSP,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype if "charset" in ctype or not ctype.startswith(
            ("text/", "application/json")) else f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _error(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def _body(self) -> dict[str, Any] | None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self._error(413, "request too large")
            return None
        raw = self.rfile.read(n) if n else b""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            self._error(415, "expected application/json")
            return None
        if not secrets.compare_digest(self.headers.get(TOKEN_HEADER) or "", self.app.token):
            self._error(403, "missing or wrong token: reload the page")
            return None
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            self._error(400, "invalid JSON")
            return None
        if not isinstance(data, dict):
            self._error(400, "expected a JSON object")
            return None
        return data

    # ---- routes

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if not self._host_ok():
            return self._error(403, "unexpected Host header")
        u = urlparse(self.path)
        path = unquote(u.path)
        try:
            if path in STATIC_FILES:
                return self._static(*STATIC_FILES[path])
            if path == "/api/state":
                return self._json(self.app.state())
            if path == "/api/sites":
                return self._json(self.app.sites())
            if path == "/api/verify":
                return self._json(self.app.verify())
            m = re.fullmatch(r"/api/scans/([^/]+)/([^/]+)", path)
            if m:
                return self._json(self.app.scan_detail(m[1], m[2]))
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", path)
            if m:
                job = self.app.job
                if not job or job.id != m[1]:
                    return self._error(404, "no such scan job")
                since = parse_qs(u.query).get("since", ["0"])[0]
                return self._json(job.view(int(since) if since.isdigit() else 0))
            m = re.fullmatch(r"/reports/([^/]+)/([^/]+)/([^/]+)", path)
            if m:
                return self._report_file(m[1], m[2], m[3], "download" in parse_qs(u.query))
        except LookupError as e:
            return self._error(404, str(e))
        self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if not self._host_ok():
            return self._error(403, "unexpected Host header")
        path = urlparse(self.path).path
        if path not in ("/api/scans", "/api/exemption"):
            return self._error(404, "not found")
        body = self._body()
        if body is None:
            return
        if path == "/api/scans":
            from ..scan.crawler import ScanError
            try:
                job = self.app.start_scan(body)
            except Busy as e:
                return self._error(409, str(e))
            except (ScanError, ValueError, FileNotFoundError) as e:
                return self._error(400, str(e))
            return self._json(job.view(), 202)
        try:
            return self._json(self.app.exemption(str(body.get("target") or "")))
        except ValueError as e:
            return self._error(400, str(e))
        except Exception as e:  # noqa: BLE001 - network errors from the register lookup
            return self._error(502, f"the business register could not be reached ({type(e).__name__})")

    def _static(self, name: str, ctype: str) -> None:
        data = (STATIC / name).read_bytes()
        if name == "index.html":
            data = data.replace(b"__TOKEN__", self.app.token.encode())
        self._send(200, data, ctype)

    def _report_file(self, site: str, stamp: str, name: str, download: bool) -> None:
        if name not in REPORT_FILES:
            raise LookupError("not a report file")
        f = self.app.scan_dir(site, stamp) / name
        if not f.is_file():
            raise LookupError("this scan has no such file")
        extra = {}
        if download or name.endswith(".md"):
            # Markdown would otherwise be shown raw; JSON only when asked.
            extra["Content-Disposition"] = f'attachment; filename="{site}-{stamp}-{name}"'
        self._send(200, f.read_bytes(), REPORT_FILES[name],
                   csp=REPORT_CSP if name.endswith(".html") else UI_CSP, extra=extra)


def make_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    return httpd


def serve(reports_dir: Path, port: int = 8765, open_browser: bool = True,
          config: str | None = None, chromium: str | None = None) -> int:
    app = App(reports_dir, config=config, chromium=chromium)
    app.settings()  # fail now, with a clear message, on a bad config file
    try:
        httpd = make_server(app, port)
    except OSError:
        if port == 0:
            raise
        httpd = make_server(app, 0)  # port taken: let the OS pick one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"AccessPilot UI: {url}\nReports in {app.reports_dir.resolve()}\n"
          "Press Ctrl+C to stop.", file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0

