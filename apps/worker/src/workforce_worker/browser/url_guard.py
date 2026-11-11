"""URL safety checks for the agent browser.

Agents browse the open web on your behalf, so the browser must never be
turned against your own infrastructure (SSRF): no localhost, private networks,
link-local / cloud metadata addresses, or non-web schemes. Every request the
page makes is checked, not just the first URL.

Defence in depth: in production also run the browser worker in a network that
has public egress only (no route to internal services), which additionally
covers DNS-rebinding tricks this resolver check cannot see.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit


class BlockedURL(ValueError):
    pass


@dataclass(frozen=True)
class DomainPolicy:
    blocked_domains: frozenset[str] = frozenset()
    # Form submission is opt-in per site: only domains you list here.
    form_submit_domains: frozenset[str] = frozenset()
    # Test/dev escape hatch for local servers. Never set in production.
    allow_private_hosts: frozenset[str] = field(default_factory=frozenset)


def _domain_matches(host: str, domains: frozenset[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


@lru_cache(maxsize=2048)
def _resolve(host: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedURL(f"cannot resolve {host}") from exc
    return tuple(sorted({info[4][0] for info in infos}))


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


_DEFAULT_POLICY = DomainPolicy()


def check_url(url: str, policy: DomainPolicy = _DEFAULT_POLICY) -> str:
    """Return the normalised URL if it is safe to load, else raise BlockedURL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise BlockedURL(f"only http(s) URLs are allowed, got {parts.scheme or 'none'!r}")
    if parts.username or parts.password:
        raise BlockedURL("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise BlockedURL("URL has no host")
    if _domain_matches(host, policy.blocked_domains):
        raise BlockedURL(f"{host} is on your blocked list")
    if host in policy.allow_private_hosts:
        return parts.geturl()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        raise BlockedURL(f"{host} is a private host")

    try:
        ips: tuple[str, ...] = (str(ipaddress.ip_address(host)),)
    except ValueError:
        ips = _resolve(host)
    if not ips or not all(_is_public(ip) for ip in ips):
        raise BlockedURL(f"{host} resolves to a private or reserved address")
    return parts.geturl()


def check_form_submission(url: str, policy: DomainPolicy) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if not _domain_matches(host, policy.form_submit_domains):
        raise BlockedURL(
            f"form submission on {host} is not enabled; add it to your allowed form sites first"
        )
