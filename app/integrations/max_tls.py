"""TLS configuration isolated to outbound MAX Bot API requests."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import certifi
import httpx

from app.config import settings

MAX_RUSSIAN_CA_BUNDLE = (
    Path(__file__).resolve().parent / "max" / "certs" / "russian_trusted_ca_bundle.pem"
)


def build_max_ssl_context() -> ssl.SSLContext:
    """Trust OS defaults, certifi's public roots, and MAX's Russian CA chain."""
    if not MAX_RUSSIAN_CA_BUNDLE.is_file():
        raise FileNotFoundError(f"MAX CA bundle is missing: {MAX_RUSSIAN_CA_BUNDLE}")

    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    # Keep regular public trust roots even when the OS and certifi stores differ.
    context.load_verify_locations(cafile=certifi.where())
    context.load_verify_locations(cafile=str(MAX_RUSSIAN_CA_BUNDLE))
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def create_max_api_client(
    *,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | httpx.Timeout = 15.0,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Construct an httpx client with MAX-only CA trust and normal verification."""
    return httpx.AsyncClient(
        base_url=(base_url or settings.max_api_base_url).rstrip("/"),
        headers=headers,
        timeout=timeout,
        verify=build_max_ssl_context(),
        **kwargs,
    )
