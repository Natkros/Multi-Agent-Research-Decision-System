"""Unit tests for the Phase 8 URL validator / SSRF guard
(`app/security/url_validation.py`)."""

from __future__ import annotations

import pytest

from app.security.url_validation import URLValidationError, is_valid_url, validate_url

_LEGIT_URLS = [
    "https://example.com/article",
    "http://docs.python.org/3/library/ipaddress.html",
    "https://sub.domain.example.co.uk:8443/path?query=1",
]

_SSRF_URLS = [
    "http://127.0.0.1/admin",
    "http://localhost:8080/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "http://10.0.0.5/internal",
    "http://192.168.1.1/",
    "http://[::1]/",  # IPv6 loopback
]

_BAD_SCHEME_URLS = [
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "gopher://example.com/",
]


@pytest.mark.parametrize("url", _LEGIT_URLS)
def test_accepts_legitimate_public_urls(url: str) -> None:
    assert validate_url(url) == url
    assert is_valid_url(url) is True


@pytest.mark.parametrize("url", _SSRF_URLS)
def test_rejects_private_and_reserved_addresses(url: str) -> None:
    with pytest.raises(URLValidationError):
        validate_url(url)
    assert is_valid_url(url) is False


@pytest.mark.parametrize("url", _BAD_SCHEME_URLS)
def test_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(URLValidationError):
        validate_url(url)
    assert is_valid_url(url) is False


def test_rejects_empty_url() -> None:
    assert is_valid_url("") is False


def test_rejects_url_with_no_hostname() -> None:
    assert is_valid_url("https:///path-only") is False
