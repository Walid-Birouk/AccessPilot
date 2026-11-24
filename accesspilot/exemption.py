"""Microenterprise self-check: does the EAA services exemption likely apply to me?

The European Accessibility Act exempts *microenterprises providing services*
(fewer than 10 persons employed AND annual turnover or balance-sheet total of at
most EUR 2 million) from its service requirements. This module looks a company
up in the public French business register (recherche-entreprises.api.gouv.fr,
free, no key) and explains what the register does and does not establish.

It is an orientation aid, not legal advice: the register gives headcount bands
per legal unit and turnover only when published; group membership and the
balance-sheet total are not available. Missing data always yields "unknown".

Given a website instead of a SIREN, it reads the site's legal pages (mentions
légales, CGV, privacy policy: GET only, a handful of requests) to find the SIREN.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

API = "https://recherche-entreprises.api.gouv.fr/search"
MICRO_LIMIT_EUR = 2_000_000

# INSEE "tranche d'effectif salarié" codes -> (label, lower bound)
HEADCOUNT: dict[str, tuple[str, int | None]] = {
    "NN": ("non renseigné", None), "00": ("0 salarié", 0), "01": ("1 ou 2", 1),
    "02": ("3 à 5", 3), "03": ("6 à 9", 6), "11": ("10 à 19", 10), "12": ("20 à 49", 20),
    "21": ("50 à 99", 50), "22": ("100 à 199", 100), "31": ("200 à 249", 200),
    "32": ("250 à 499", 250), "41": ("500 à 999", 500), "42": ("1000 à 1999", 1000),
    "51": ("2000 à 4999", 2000), "52": ("5000 à 9999", 5000), "53": ("10000 et plus", 10000),
}

# Providers whose SIREN appears in many shops' legal pages (hosting, payment).
THIRD_PARTY_SIRENS = {"424761419", "510909807", "431303775", "423093459", "433115904", "839100575"}

LEGAL_LINKS = [
    re.compile(r"mentions?[-_ ]?l[ée]gales?|legal[-_ ]?notice|informations?[-_ ]?l[ée]gales?|imprint", re.I),
    re.compile(r"\bcgv\b|conditions[-_ ]g[ée]n[ée]rales|terms[-_ ]of[-_ ]service", re.I),
    re.compile(r"confidentialit|privacy|donn[ée]es[-_ ]personnelles", re.I),
]
FALLBACK_PATHS = ["/mentions-legales", "/pages/mentions-legales", "/policies/legal-notice",
                  "/content/2-mentions-legales", "/policies/terms-of-service", "/pages/cgv"]
MAX_FETCHES = 6

ID_NEAR = re.compile(
    r"(?:SIRE[NT]|R\.?\s?C\.?\s?S\.?|RCS|RM\b|immatricul\w*|N°\s?d'identification"
    r"|registre\s+du\s+commerce|num[ée]ro\s+d'entreprise|identifiant)"
    r"[^0-9]{0,60}((?:\d[\s. ]?){9})", re.I)
BEFORE_RCS = re.compile(r"((?:\d[\s. ]?){9})\s*R\.?\s?C\.?\s?S\b", re.I)
VAT = re.compile(r"\bFR\s?[0-9A-Z]{2}\s?((?:\d[\s. ]?){9})\b")


def luhn_ok(siren: str) -> bool:
    if siren == "356000000":  # La Poste: the documented exception
        return True
    total = 0
    for i, ch in enumerate(reversed(siren)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def normalise_siren(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 14:  # a SIRET: the SIREN is its first 9 digits
        digits = digits[:9]
    return digits if len(digits) == 9 and luhn_ok(digits) else None


def extract_sirens(text: str) -> list[str]:
    """Valid SIRENs in order of appearance, known third parties removed."""
    hits: list[tuple[int, str]] = []
    for rx in (ID_NEAR, BEFORE_RCS, VAT):
        for m in rx.finditer(text):
            d = re.sub(r"\D", "", m.group(1))[:9]
            if len(d) == 9 and luhn_ok(d) and d not in THIRD_PARTY_SIRENS:
                hits.append((m.start(1), d))
    found: list[str] = []
    for _, d in sorted(hits):
        if d not in found:
            found.append(d)
    return found


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._label: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "a":
            self._href, self._label = dict(attrs).get("href") or "", []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._label)))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.text.append(data)
        if self._href is not None:
            self._label.append(data)


def parse_page(html: str) -> tuple[str, list[tuple[str, str]]]:
    p = _Page()
    p.feed(html)
    return re.sub(r"\s+", " ", " ".join(p.text)), p.links


def legal_pages(base: str, links: list[tuple[str, str]]) -> list[str]:
    """Same-host links to legal pages: notice first, then terms, then privacy."""
    host = urlparse(base).netloc
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for href, label in links:
        for rank, rx in enumerate(LEGAL_LINKS):
            if rx.search(href) or rx.search(label):
                u = urljoin(base, href).split("#")[0].split("?")[0]
                if urlparse(u).netloc == host and u not in seen:
                    seen.add(u)
                    ranked.append((rank, u))
                break
    return [u for _, u in sorted(ranked, key=lambda t: t[0])]


def find_siren_on_site(url: str, user_agent: str, timeout_s: int = 20) -> tuple[list[str], list[str]]:
    """(SIRENs found, pages read). Static HTML only."""
    if "://" not in url:
        url = "https://" + url
    read: list[str] = []
    with httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout_s,
                      follow_redirects=True) as client:
        home = client.get(url)
        home.raise_for_status()
        read.append(str(home.url))
        text, links = parse_page(home.text)
        sirens = extract_sirens(text)
        candidates = legal_pages(str(home.url), links)
        candidates += [urljoin(str(home.url), p) for p in FALLBACK_PATHS
                       if urljoin(str(home.url), p) not in candidates]
        for page in candidates[:MAX_FETCHES]:
            if sirens:
                break
            try:
                r = client.get(page)
            except httpx.HTTPError:
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                continue
            read.append(str(r.url))
            for s in extract_sirens(parse_page(r.text)[0]):
                if s not in sirens:
                    sirens.append(s)
    return sirens, read


def lookup_siren(siren: str, client: httpx.Client | None = None) -> dict[str, Any] | None:
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        for attempt in range(3):
            try:
                r = client.get(API, params={"q": siren})
            except httpx.TransportError:
                time.sleep(1 + attempt)
                continue
            if r.status_code == 429:  # documented limit: 7 requests/s
                time.sleep(1 + attempt)
                continue
            r.raise_for_status()
            for res in r.json().get("results", []):
                if res.get("siren") == siren:
                    return res
            return None
        raise RuntimeError("business register unreachable or rate-limited three times")
    finally:
        if own:
            client.close()


LIKELY_EXEMPT, NOT_EXEMPT, UNKNOWN = "likely_exempt", "not_exempt", "unknown"


@dataclass
class ExemptionResult:
    status: str
    siren: str | None
    company: str | None = None
    headcount: str | None = None
    category: str | None = None
    turnover: int | None = None
    turnover_year: str | None = None
    reasons: list[str] = field(default_factory=list)


def _turnover(company: dict[str, Any]) -> tuple[int | None, str | None]:
    fin = company.get("finances") or {}
    if not fin:
        return None, None
    year = max(fin)
    ca = (fin[year] or {}).get("ca")
    return (int(ca) if ca is not None else None), year


def decide(company: dict[str, Any] | None, siren: str | None) -> ExemptionResult:
    """Pure function: register record -> exemption orientation with reasons."""
    if siren is None:
        return ExemptionResult(UNKNOWN, None, reasons=["no SIREN found: the exemption cannot be checked"])
    if company is None:
        return ExemptionResult(UNKNOWN, siren, reasons=[f"SIREN {siren} not found in the register"])

    band = company.get("tranche_effectif_salarie") or "NN"
    label, low = HEADCOUNT.get(band, (band, None))
    cat = company.get("categorie_entreprise")
    ca, year = _turnover(company)
    res = ExemptionResult(UNKNOWN, siren, company.get("nom_complet"), label, cat, ca, year)
    r = res.reasons

    if company.get("etat_administratif") == "C":
        r.append("the company is closed (cessée) in the register")
        return res
    if company.get("statut_diffusion") not in (None, "O"):
        r.append("the company's register data is not public: check by hand")
        return res
    if cat in ("ETI", "GE"):
        res.status = NOT_EXEMPT
        r.append(f"INSEE category {cat} (computed at group level): not a microenterprise")
        return res
    if low is not None and low >= 10:
        res.status = NOT_EXEMPT
        r.append(f"{label} employees in the legal unit: 10 or more, not a microenterprise")
        return res
    if low is None:
        r.append("headcount not published in the register")
        return res
    # Fewer than 10 employees in the legal unit.
    if ca is not None and ca <= MICRO_LIMIT_EUR:
        res.status = LIKELY_EXEMPT
        r.append(f"{label} employees and turnover {ca:,} EUR ({year}): within the microenterprise "
                 "thresholds".replace(",", " "))
    elif ca is not None:
        r.append(f"{label} employees but turnover {ca:,} EUR ({year}) above EUR 2M: the exemption "
                 "still applies if the balance-sheet total is at most EUR 2M; check your "
                 "accounts".replace(",", " "))
    else:
        r.append(f"{label} employees, turnover not published: check your turnover or "
                 "balance-sheet total against EUR 2M")
    r.append("headcount is per legal unit: if the company belongs to a group, group-level "
             "figures may apply")
    return res


def check_target(target: str, user_agent: str | None = None,
                 log: Any = None) -> ExemptionResult:
    """SIREN, SIRET or a shop's address -> exemption orientation.

    Raises ValueError for a number that is not a valid SIREN/SIRET. ``log`` gets
    one-line notes (pages read, several SIRENs found).
    """
    from .config import Settings

    log = log or (lambda _m: None)
    target = target.strip()
    if not target:
        raise ValueError("enter a SIREN, a SIRET or the shop's address")
    numeric = re.fullmatch(r"[\d\s.]+", target) is not None
    siren = normalise_siren(target) if numeric else None
    if numeric and siren is None:
        raise ValueError(f"{target!r} is not a valid SIREN or SIRET")
    if siren is None:
        sirens, read = find_siren_on_site(target, user_agent or Settings().user_agent)
        log(f"Read {len(read)} page(s) of {target}.")
        if len(sirens) > 1:
            log(f"Several SIRENs found ({', '.join(sirens)}); using the first. Pass the right "
                "one explicitly if it is not yours.")
        siren = sirens[0] if sirens else None
    return decide(lookup_siren(siren) if siren else None, siren)
