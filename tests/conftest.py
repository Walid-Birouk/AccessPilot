"""Shared fixtures. No network, no LLM; browser tests are marked and skipped without Chromium."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from accesspilot.model import Finding, Page, ReviewItem, Scan  # noqa: E402


def finding(n: int, rule: str = "image-alt", template: str = "product", impact: str = "critical",
            selector: str | None = None, url: str | None = None, html: str | None = None,
            scan_id: str = "s1") -> Finding:
    selector = selector or f"#el{n}"
    html = html if html is not None else f"<img id='el{n}'>"
    from accesspilot.scan.crawler import fingerprint
    return Finding(
        evidence_id=f"{scan_id}-{n:04d}", fingerprint=fingerprint(template, rule, selector, html),
        rule=rule, impact=impact, help=f"help {rule}", help_url=f"https://example.org/{rule}",
        wcag=["wcag2a", "wcag111"], url=url or f"https://shop.example/{template}/{n}",
        template=template, selector=selector, html=html)


def make_scan(findings: list[Finding] | None = None, scan_id: str = "s1", site: str = "shop.example",
              templates: tuple[str, ...] = ("home", "product", "cart"),
              started: str = "2026-01-01T10:00:00+00:00") -> Scan:
    pages = [Page(url=f"https://{site}/{t}", template=t, status=200, title=t.title(), violations=1)
             for t in templates]
    return Scan(
        scan_id=scan_id, site=site, start_url=f"https://{site}/", started=started,
        finished=started, tool_versions={"accesspilot": "test", "axe_core": "4.14.0", "chromium": "1"},
        settings={"max_pages": 20, "max_depth": 2, "per_template": 3, "respect_robots": True},
        pages=pages, findings=findings or [],
        needs_review=[ReviewItem("color-contrast", "contrast", "https://x", f"https://{site}/home",
                                 "home", 2)],
    )


def chromium_path() -> str | None:
    """A Chromium for browser tests: ACCESSPILOT_CHROMIUM, else Playwright's own, else None."""
    env = os.environ.get("ACCESSPILOT_CHROMIUM")
    if env:
        return env
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
        if Path(path).exists():
            return path
    except Exception:
        pass
    return shutil.which("chromium") or shutil.which("chromium-browser")


@pytest.fixture(scope="session")
def chromium() -> str:
    path = chromium_path()
    if not path:
        pytest.skip("no Chromium available (run `playwright install chromium`)")
    return path
