from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.models import Account
from app.web.db import get_session


@dataclass(frozen=True)
class Principal:
    user_id: int
    is_demo: bool = False


def verify_max_init_data(init_data: str, *, now: int | None = None, max_age: int = 3600) -> int:
    """Validate signed MAX Bridge initData and return its authenticated user ID."""
    if not settings.max_bot_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MAX authentication is not configured")
    if len(init_data) > 8192:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MAX initData")

    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=64,
        )
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MAX initData") from None
    if len({key for key, _ in pairs}) != len(pairs):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MAX initData")
    values = dict(pairs)
    received_hash = values.pop("hash", None)
    if (
        not received_hash
        or len(received_hash) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in received_hash)
        or "auth_date" not in values
        or "user" not in values
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MAX initData")

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", settings.max_bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash.lower()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MAX signature check failed")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        user_id = int(user["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MAX identity data") from None
    timestamp = int(time.time()) if now is None else now
    if auth_date > timestamp + 60 or timestamp - auth_date > max_age:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MAX authorization data has expired")
    return user_id


async def get_principal(
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None, alias="X-Demo-User"),
) -> Principal:
    if x_demo_user is not None and settings.demo_auth_enabled:
        try:
            return Principal(user_id=int(x_demo_user), is_demo=True)
        except ValueError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid demo user") from None

    if authorization and authorization.startswith("tma "):
        return Principal(user_id=verify_max_init_data(authorization[4:]))
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Open this app from MAX to sign in")


async def get_account(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Account:
    account = await session.get(Account, principal.user_id)
    if account is None or not account.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not registered or is blocked")
    if principal.is_demo and not account.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo access is limited to seed accounts")
    return account


def require_role(*roles: str):
    async def dependency(account: Account = Depends(get_account)) -> Account:
        if account.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return account

    return dependency
