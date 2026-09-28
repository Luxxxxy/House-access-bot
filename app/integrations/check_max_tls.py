"""Verify TLS trust to MAX without authenticating or requiring an API token."""

from __future__ import annotations

import asyncio

import httpx

from app.integrations.max_tls import create_max_api_client


async def check_max_tls() -> int:
    try:
        async with create_max_api_client(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            response = await client.get("/")
    except httpx.ConnectError as exc:
        cause = exc.__cause__ or exc
        print(f"TLS connection failed: {type(cause).__name__}: {cause}")
        return 1
    except httpx.RequestError as exc:
        print(f"MAX HTTPS request failed: {type(exc).__name__}: {exc}")
        return 1

    # The unauthenticated root may legitimately return 401/404. Any HTTP response
    # proves the TLS handshake completed with certificate verification enabled.
    print(f"TLS connection verified: HTTP {response.status_code}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(check_max_tls()))


if __name__ == "__main__":
    main()
