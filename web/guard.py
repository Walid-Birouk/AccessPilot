"""Limits for scans started by anonymous visitors of the public demo.

- ``public_url_allowed``: a scan may only reach public web addresses. The host
  must resolve to globally routable IPs only (no loopback, private, link-local
  or cloud metadata ranges), on the standard web ports. The crawler asks this
  for every request the browser makes, and once more where a navigation landed.
- ``RateLimiter``: per-visitor and global quotas, so one visitor cannot use the
  demo to hammer a shop or exhaust the free host.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections import deque
from urllib.parse import urlparse

_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet",
                     ".example", ".invalid", ".test")
_DNS_TTL_S = 60
_dns_cache: dict[str, tuple[float, bool]] = {}
_dns_lock = threading.Lock()


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def host_is_public(host: str) -> bool:
    host = (host or "").strip().rstrip(".").lower()
    literal = host.strip("[]")
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        return _ip_is_public(literal)
    if not host or host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or "." not in host:
        return False
    now = time.monotonic()
    with _dns_lock:
        hit = _dns_cache.get(host)
        if hit and now - hit[0] < _DNS_TTL_S:
            return hit[1]
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ok = bool(infos) and all(_ip_is_public(str(i[4][0])) for i in infos)
    except (OSError, UnicodeError):
        ok = False
    with _dns_lock:
        _dns_cache[host] = (now, ok)
    return ok


def public_url_allowed(url: str) -> bool:
    """True for http(s) URLs on ports 80/443 whose host resolves only to public IPs.
    ``data:`` and ``blob:`` URLs carry no network request and are allowed."""
    if url.startswith(("data:", "blob:")):
        return True
    try:
        p = urlparse(url)
        port = p.port
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or p.username or p.password:
        return False
    if port not in (None, 80, 443):
        return False
    return host_is_public(p.hostname or "")


class Limited(Exception):
    """A quota was reached. The message is shown to the visitor as is."""


class RateLimiter:
    """Sliding-window quotas: per client per hour, and for everyone per day."""

    def __init__(self, per_client_per_hour: int, global_per_day: int):
        self.per_client = per_client_per_hour
        self.global_per_day = global_per_day
        self._clients: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self, client: str, now: float | None = None) -> None:
        """Count one scan for ``client``, or raise ``Limited`` without counting it."""
        now = time.time() if now is None else now
        with self._lock:
            while self._all and now - self._all[0] > 86400:
                self._all.popleft()
            q = self._clients.setdefault(client, deque())
            while q and now - q[0] > 3600:
                q.popleft()
            if len(self._all) >= self.global_per_day:
                raise Limited("The demo has reached today's scan limit. The sample reports are "
                              "still here, and the command line tool has no limit.")
            if len(q) >= self.per_client:
                wait = int((3600 - (now - q[0])) // 60) + 1
                raise Limited(f"You have used your {self.per_client} live scans for this hour. "
                              f"Try again in about {wait} min, or browse the sample reports.")
            q.append(now)
            self._all.append(now)
            if len(self._clients) > 10000:   # forget idle clients
                for k in [k for k, v in self._clients.items() if not v]:
                    del self._clients[k]
