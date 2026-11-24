"""A tiny local shop for browser tests: pretty URLs, a strict CSP, a 404, a 500,
and logout / add-to-cart links the crawler must never follow."""
from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SITE = Path(__file__).parent / "fixtures" / "site"


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *args: object) -> None:  # keep test output quiet
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?")[0]
        type(self).hits.append(self.path)
        if path == "/boom":
            return self._send(500, b"error", "text/plain")
        if path == "/robots.txt":
            return self._send(200, (SITE / "robots.txt").read_bytes(), "text/plain")
        rel = path.strip("/") or "index"
        f = SITE / f"{rel}.html"
        if not f.exists():
            return self._send(404, b"<!doctype html><title>404</title><p>not found", "text/html")
        self._send(200, f.read_bytes(), "text/html; charset=utf-8")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        # A strict CSP: inline scripts are forbidden. axe must still run.
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def serve() -> Iterator[tuple[str, list[str]]]:
    """Yields (base URL, list of requested paths)."""
    handler = type("Handler", (_Handler,), {"hits": []})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", handler.hits
    finally:
        httpd.shutdown()
        httpd.server_close()
