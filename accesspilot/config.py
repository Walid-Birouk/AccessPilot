"""Scan settings: sensible defaults, overridable from a TOML file and CLI flags.

Precedence: CLI flag > ``--config`` file (or ``accesspilot.toml`` in the current
directory) > defaults below. No global state: the resolved ``Settings`` object
is passed explicitly to every stage.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import __version__

# Page templates that matter for an online shop, in priority order: the purchase
# path first (a blocking defect there stops a sale), then product discovery.
# Patterns are matched as substrings of the lower-cased URL path, except "/"
# which only matches the home page. First match wins.
DEFAULT_TEMPLATES: dict[str, list[str]] = {
    "checkout": ["/checkout", "/commande", "/order", "/paiement", "/payment"],
    "cart": ["/cart", "/panier", "/basket"],
    "account": ["/account", "/compte", "/login", "/connexion", "/my-account", "/mon-compte"],
    "product": ["/products/", "/product/", "/produit", "/p/", "/article/"],
    "category": ["/collections/", "/collection/", "/categorie", "/category", "/c/", "/rayon"],
    "search": ["/search", "/recherche"],
    "contact": ["/contact"],
    "home": ["/"],
}

# Lower number = more important. Used to order the fix plan.
TEMPLATE_PRIORITY = {"checkout": 0, "cart": 1, "account": 2, "product": 3,
                     "category": 4, "search": 5, "home": 6, "contact": 7}

WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


@dataclass
class Settings:
    max_pages: int = 20
    max_depth: int = 2
    per_template: int = 3          # pages sampled per template: same template, same defects
    time_budget_s: int = 600
    page_timeout_s: int = 30
    settle_ms: int = 3000          # wait for network idle after load, at most this long
    delay_s: float = 0.5           # politeness pause between page loads
    breaker_threshold: int = 5     # stop after this many 429/5xx responses
    respect_robots: bool = True
    user_agent: str = f"AccessPilot/{__version__} (+https://github.com/Walid-Birouk/AccessPilot)"
    locale: str = "fr"             # axe-core message language: "fr" or "en"
    wcag_tags: list[str] = field(default_factory=lambda: list(WCAG_TAGS))
    templates: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_TEMPLATES))
    extra_urls: list[str] = field(default_factory=list)
    chromium_path: str | None = None

    def public(self) -> dict[str, Any]:
        """What gets recorded in scan.json (no machine-specific paths)."""
        d = asdict(self)
        d.pop("chromium_path", None)
        return d


def load_settings(path: str | Path | None = None, **overrides: Any) -> Settings:
    """Defaults <- TOML ``[scan]`` table <- non-None keyword overrides."""
    s = Settings()
    cfg_path = Path(path) if path else Path("accesspilot.toml")
    if path and not cfg_path.exists():
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    if cfg_path.exists():
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        _apply(s, data.get("scan", {}), source=str(cfg_path))
        if "templates" in data:
            s.templates = {str(k): [str(p) for p in v] for k, v in data["templates"].items()}
    _apply(s, {k: v for k, v in overrides.items() if v is not None}, source="command line")
    if s.chromium_path is None:
        s.chromium_path = os.environ.get("ACCESSPILOT_CHROMIUM") or None
    _check(s)
    return s


def _apply(s: Settings, values: dict[str, Any], source: str) -> None:
    known = {f.name for f in fields(Settings)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"{source}: unknown setting '{key}'")
        setattr(s, key, value)


def _check(s: Settings) -> None:
    for name in ("max_pages", "per_template", "time_budget_s", "page_timeout_s", "breaker_threshold"):
        if int(getattr(s, name)) < 1:
            raise ValueError(f"setting '{name}' must be >= 1")
    if s.max_depth < 0 or s.settle_ms < 0 or s.delay_s < 0:
        raise ValueError("max_depth, settle_ms and delay_s must be >= 0")
    if s.locale not in ("fr", "en"):
        raise ValueError("locale must be 'fr' or 'en'")
