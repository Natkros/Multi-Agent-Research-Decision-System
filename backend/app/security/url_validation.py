"""URL validation / SSRF protection (Phase 8, brief §14/§27).

Applied before anything treats a URL as fetchable: `SearchProvider`
implementations that return third-party URLs (`app/tools/search_provider.py`)
filter results through this module before handing them to a caller, so a
malicious/compromised search result can't smuggle a
`http://169.254.169.254/...` (cloud metadata) or `http://127.0.0.1:...`
(internal service) URL further into the pipeline.

Scope note: hostnames that are *not* IP literals (the common case for real
search results) are accepted without a DNS lookup here -- resolving every
candidate URL would add a network round trip (and its own SSRF-via-DNS-
rebinding surface) to a code path that, today, only ever stores the URL as
metadata and never actually fetches its contents. If/when a component starts
fetching page bodies by URL, resolve-then-validate the resolved IP at fetch
time in addition to this check.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}

# Well-known SSRF targets that are hostnames rather than IP literals, so the
# IP-range check below wouldn't catch them.
_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
}


class URLValidationError(ValueError):
    pass


def _is_private_or_reserved_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP literal -- hostname, handled separately
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str) -> str:
    """Returns `url` unchanged if it passes; raises `URLValidationError`
    otherwise. Rejects non-http(s) schemes and URLs that point at a private,
    loopback, link-local (includes the 169.254.169.254 cloud metadata
    address), or otherwise reserved IP address."""
    if not url:
        raise URLValidationError("URL must not be empty")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise URLValidationError(f"unsupported URL scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL has no hostname")
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise URLValidationError(f"blocked hostname: {hostname!r}")
    if _is_private_or_reserved_ip(hostname):
        raise URLValidationError(f"URL resolves to a private/reserved address: {hostname!r}")

    return url


def is_valid_url(url: str) -> bool:
    try:
        validate_url(url)
        return True
    except URLValidationError:
        return False
